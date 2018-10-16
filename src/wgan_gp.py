# ---------------------------------------------------------
# TensorFlow WGAN-GP Implementation
# Licensed under The MIT License [see LICENSE for details]
# Written by Cheng-Bin Jin
# Email: sbkim0407@gmail.com
# ---------------------------------------------------------
import collections
import numpy as np
import tensorflow as tf
from tensorflow.contrib.layers import flatten
import matplotlib as mpl
mpl.use('TkAgg')  # or whatever other backend that you want to solve Segmentation fault (core dumped)
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# noinspection PyPep8Naming
import tensorflow_utils as tf_utils
import utils as utils


class WGAN_GP(object):
    def __init__(self, sess, flags, dataset):
        self.sess = sess
        self.flags = flags
        self.dataset = dataset
        self.image_size = dataset.image_size

        if self.flags.dataset == 'mnist':
            self.gen_c = [4096, 128, 64]
            self.dis_c = [64, 128, 256]

        self._build_net()
        self._tensorboard()
        print("Initialized WGAN SUCCESS!")

    def _build_net(self):
        self.Y = tf.placeholder(tf.float32, shape=[None, *self.image_size], name='real_data')
        self.z = tf.placeholder(tf.float32, shape=[None, self.flags.z_dim], name='latent_vector')

        self.g_samples = self.generator(self.z)
        _, d_logit_real = self.discriminator(self.Y)
        _, d_logit_fake = self.discriminator(self.g_samples, is_reuse=True)

        # discriminator loss
        self.wgan_d_loss = tf.reduce_mean(d_logit_fake) - tf.reduce_mean(d_logit_real)
        # generator loss
        self.g_loss = -tf.reduce_mean(d_logit_fake)

        d_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='d_')
        g_vars = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='g_')

        # gradient penalty
        self.gp_loss = self.gradient_penalty()
        self.d_loss = self.wgan_d_loss + self.flags.lambda_ * self.gp_loss

        # Optimizers for generator and discriminator
        self.gen_optim = tf.train.AdamOptimizer(
            learning_rate=self.flags.learning_rate, beta1=0.5, beta2=0.9).minimize(self.g_loss, var_list=g_vars)
        self.dis_optim = tf.train.AdamOptimizer(
            learning_rate=self.flags.learning_rate, beta1=0.5, beta2=0.9).minimize(self.d_loss, var_list=d_vars)

    def gradient_penalty(self):
        alpha = tf.random_uniform(shape=[self.flags.batch_size, 1], minval=0., maxval=1.)
        differences = self.g_samples - self.Y
        interpolates = self.Y + (alpha * differences)
        gradients = tf.gradients(self.discriminator(interpolates, is_reuse=True), [interpolates])[0]
        slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1, 2, 3]))
        gradient_penalty = tf.reduce_mean((slopes-1.)**2)

        return gradient_penalty

    def _tensorboard(self):
        tf.summary.scalar('loss/wgan_d_loss', self.wgan_d_loss)
        tf.summary.scalar('loss/gp_loss', self.gp_loss)
        tf.summary.scalar('loss/d_loss', self.d_loss)
        tf.summary.scalar('loss/g_loss', self.g_loss)

        self.summary_op = tf.summary.merge_all()

    def generator(self, data, name='g_'):
        with tf.variable_scope(name):
            data_flatten = flatten(data)

            # from (N, 128) to (N, 4, 4, 256)
            h0_linear = tf_utils.linear(data_flatten, self.gen_c[0], name='h0_linear')
            h0_relu = tf.nn.relu(h0_linear, name='h0_relu')
            h0_reshape = tf.reshape(h0_relu, [tf.shape(h0_relu)[0], 4, 4, int(self.gen_c[0]/(4*4))])

            # from (N, 4, 4, 256) to (N, 8, 8, 128)
            h1_deconv = tf_utils.deconv2d(h0_reshape, self.gen_c[1], k_h=5, k_w=5, name='h1_deconv2d')
            h1_relu = tf.nn.relu(h1_deconv, name='h1_relu')

            # from (N, 8, 8, 128) to (N, 16, 16, 64)
            h2_deconv = tf_utils.deconv2d(h1_relu, self.gen_c[2], k_h=5, k_w=5, name='h2_deconv2d')
            h2_relu = tf.nn.relu(h2_deconv, name='h2_relu')

            # from (N, 16, 16, 64) to (N, 32, 32, 1)
            output = tf_utils.deconv2d(h2_relu, self.image_size[2], k_h=5, k_w=5, name='h3_deconv2d')

            return tf.nn.tanh(output)

    def discriminator(self, data, name='d_', is_reuse=False):
        with tf.variable_scope(name) as scope:
            if is_reuse is True:
                scope.reuse_variables()

            # from (N, 32, 32, 1) to (N, 16, 16, 64)
            h0_conv = tf_utils.conv2d(data, self.dis_c[0], k_h=5, k_w=5, name='h0_conv2d')
            h0_lrelu = tf_utils.lrelu(h0_conv, name='h0_lrelu')

            # from (N, 16, 16, 64) to (N, 8, 8, 128)
            h1_conv = tf_utils.conv2d(h0_lrelu, self.dis_c[1], k_h=5, k_w=5, name='h1_conv2d')
            h1_lrelu = tf_utils.lrelu(h1_conv, name='h1_lrelu')

            # from (N, 8, 8, 128) to (N, 4, 4, 256)
            h2_conv = tf_utils.conv2d(h1_lrelu, self.dis_c[2], k_h=5, k_w=5, name='h2_conv2d')
            h2_lrelu = tf_utils.lrelu(h2_conv, name='h2_lrelu')

            # from (N, 4, 4, 256) to (N, 4096) and to (N, 1)
            h2_flatten = flatten(h2_lrelu)
            h3_linear = tf_utils.linear(h2_flatten, 1, name='h3_linear')

            return tf.nn.sigmoid(h3_linear), h3_linear

    def train_step(self):
        wgan_d_loss, gp_loss, d_loss = None, None, None

        # train discriminator
        for idx in range(self.flags.num_critic):
            batch_imgs = self.dataset.train_next_batch(batch_size=self.flags.batch_size)
            dis_feed = {self.z: self.sample_z(num=self.flags.batch_size), self.Y: batch_imgs}
            dis_run = [self.dis_optim, self.wgan_d_loss, self.gp_loss, self.d_loss]
            _, wgan_d_loss, gp_loss, d_loss = self.sess.run(dis_run, feed_dict=dis_feed)

        # train generator
        batch_imgs = self.dataset.train_next_batch(batch_size=self.flags.batch_size)
        gen_feed = {self.z: self.sample_z(num=self.flags.batch_size), self.Y: batch_imgs}
        _, g_loss, summary = self.sess.run([self.gen_optim, self.g_loss, self.summary_op], feed_dict=gen_feed)

        return [wgan_d_loss, gp_loss, d_loss, g_loss], summary

    def sample_imgs(self):
        g_feed = {self.z: self.sample_z(num=self.flags.sample_batch)}
        y_fakes = self.sess.run(self.g_samples, feed_dict=g_feed)

        return [y_fakes]

    def sample_z(self, num=64):
        return np.random.uniform(-1., 1., size=[num, self.flags.z_dim])

    def print_info(self, loss, iter_time):
        if np.mod(iter_time, self.flags.print_freq) == 0:
            ord_output = collections.OrderedDict([('cur_iter', iter_time), ('tar_iters', self.flags.iters),
                                                  ('batch_size', self.flags.batch_size),
                                                  ('wgan_d_loss', loss[0]), ('gp_loss', loss[1]),
                                                  ('d_loss', loss[2]), ('g_loss', loss[3]),
                                                  ('dataset', self.flags.dataset),
                                                  ('gpu_index', self.flags.gpu_index)])

            utils.print_metrics(iter_time, ord_output)

    def plots(self, imgs_, iter_time, save_file):
        # reshape image from vector to (N, H, W, C)
        imgs_fake = np.reshape(imgs_[0], (self.flags.sample_batch, *self.image_size))

        imgs = []
        for img in imgs_fake:
            imgs.append(img)

        # parameters for plot size
        scale, margin = 0.04, 0.01
        n_cols, n_rows = int(np.sqrt(len(imgs))), int(np.sqrt(len(imgs)))
        cell_size_h, cell_size_w = imgs[0].shape[0] * scale, imgs[0].shape[1] * scale

        fig = plt.figure(figsize=(cell_size_w * n_cols, cell_size_h * n_rows))  # (column, row)
        gs = gridspec.GridSpec(n_rows, n_cols)  # (row, column)
        gs.update(wspace=margin, hspace=margin)

        imgs = [utils.inverse_transform(imgs[idx]) for idx in range(len(imgs))]

        # save more bigger image
        for col_index in range(n_cols):
            for row_index in range(n_rows):
                ax = plt.subplot(gs[row_index * n_cols + col_index])
                plt.axis('off')
                ax.set_xticklabels([])
                ax.set_yticklabels([])
                ax.set_aspect('equal')
                if self.image_size[2] == 3:
                    plt.imshow((imgs[row_index * n_cols + col_index]).reshape(
                        self.image_size[0], self.image_size[1], self.image_size[2]), cmap='Greys_r')
                elif self.image_size[2] == 1:
                    plt.imshow((imgs[row_index * n_cols + col_index]).reshape(
                        self.image_size[0], self.image_size[1]), cmap='Greys_r')
                else:
                    raise NotImplementedError

        plt.savefig(save_file + '/sample_{}.png'.format(str(iter_time)), bbox_inches='tight')
        plt.close(fig)