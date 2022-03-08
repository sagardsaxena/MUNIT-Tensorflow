import tensorflow as tf
import tensorflow_addons as tfa
from src.models.munit_tf3.utils import pytorch_kaiming_weight_factor

factor, mode, uniform = pytorch_kaiming_weight_factor(a=0.0, uniform=False)
weight_init = tf.compat.v1.keras.initializers.VarianceScaling(scale=factor, mode=(mode).lower(), distribution=("uniform" if uniform else "truncated_normal"))
weight_regularizer = tf.keras.regularizers.l2(l=0.5 * (0.0001))

##################################################################################
# Layer
##################################################################################

def conv(x, channels, kernel=4, stride=2, pad=0, pad_type='zero', use_bias=True, scope='conv'):
    with tf.compat.v1.variable_scope(scope):
        if scope.__contains__("discriminator") :
            weight_init = tf.compat.v1.random_normal_initializer(mean=0.0, stddev=0.02)
        else :
            weight_init = tf.compat.v1.keras.initializers.VarianceScaling(scale=2.0)

        if pad > 0:
            h = x.get_shape().as_list()[1]
            if h % stride == 0:
                pad = pad * 2
            else:
                pad = max(kernel - (h % stride), 0)

            pad_top = pad // 2
            pad_bottom = pad - pad_top
            pad_left = pad // 2
            pad_right = pad - pad_left

            if pad_type == 'zero':
                x = tf.pad(tensor=x, paddings=[[0, 0], [pad_top, pad_bottom], [pad_left, pad_right], [0, 0]])
            if pad_type == 'reflect':
                x = tf.pad(tensor=x, paddings=[[0, 0], [pad_top, pad_bottom], [pad_left, pad_right], [0, 0]], mode='REFLECT')

        x = tf.compat.v1.layers.conv2d(inputs=x, filters=channels,
                             kernel_size=kernel, kernel_initializer=weight_init,
                             kernel_regularizer=weight_regularizer,
                             strides=stride, use_bias=use_bias)

        return x

def fully_connected(x, units, use_bias=True, scope='fully_connected'):
    with tf.compat.v1.variable_scope(scope):
        x = flatten(x)
        x = tf.compat.v1.layers.dense(x, units=units, kernel_initializer=weight_init,
                            kernel_regularizer=weight_regularizer,
                            use_bias=use_bias)

        return x

def flatten(x) :
    return tf.compat.v1.layers.flatten(x)

##################################################################################
# Residual-block
##################################################################################

def resblock(x_init, channels, use_bias=True, scope='resblock'):
    with tf.compat.v1.variable_scope(scope):
        with tf.compat.v1.variable_scope('res1'):
            x = conv(x_init, channels, kernel=3, stride=1, pad=1, pad_type='reflect', use_bias=use_bias)
            x = instance_norm(x)
            x = relu(x)

        with tf.compat.v1.variable_scope('res2'):
            x = conv(x, channels, kernel=3, stride=1, pad=1, pad_type='reflect', use_bias=use_bias)
            x = instance_norm(x)

        return x + x_init

def adaptive_resblock(x_init, channels, gamma1, beta1, gamma2, beta2, use_bias=True, scope='adaptive_resblock') :
    with tf.compat.v1.variable_scope(scope):
        with tf.compat.v1.variable_scope('res1'):
            x = conv(x_init, channels, kernel=3, stride=1, pad=1, pad_type='reflect', use_bias=use_bias)
            x = adaptive_instance_norm(x, gamma1, beta1)
            x = relu(x)

        with tf.compat.v1.variable_scope('res2'):
            x = conv(x, channels, kernel=3, stride=1, pad=1, pad_type='reflect', use_bias=use_bias)
            x = adaptive_instance_norm(x, gamma2, beta2)

        return x + x_init

##################################################################################
# Sampling
##################################################################################

def down_sample(x) :
    return tf.compat.v1.layers.average_pooling2d(x, pool_size=3, strides=2, padding='SAME')

def up_sample(x, scale_factor=2):
    _, h, w, _ = x.get_shape().as_list()
    new_size = [h * scale_factor, w * scale_factor]
    return tf.image.resize(x, size=new_size, method=tf.image.ResizeMethod.NEAREST_NEIGHBOR)

def adaptive_avg_pooling(x):
    # global average pooling
    gap = tf.reduce_mean(input_tensor=x, axis=[1, 2], keepdims=True)

    return gap

##################################################################################
# Activation function
##################################################################################

def lrelu(x, alpha=0.01):
    # pytorch alpha is 0.01
    return tf.nn.leaky_relu(x, alpha)


def relu(x):
    return tf.nn.relu(x)


def tanh(x):
    return tf.tanh(x)

##################################################################################
# Normalization function
##################################################################################

def adaptive_instance_norm(content, gamma, beta, epsilon=1e-5):
    # gamma, beta = style_mean, style_std from MLP

    c_mean, c_var = tf.nn.moments(x=content, axes=[1, 2], keepdims=True)
    c_std = tf.sqrt(c_var + epsilon)

    return gamma * ((content - c_mean) / c_std) + beta


def instance_norm(x, scope='instance_norm'):
    return tfa.layers.InstanceNormalization(epsilon=1e-05,
                                            center=True,
                                            scale=True)(x)
#     return tf.contrib.layers.instance_norm(x,
#                                            epsilon=1e-05,
#                                            center=True, scale=True,
#                                            scope=scope)

def layer_norm(x, scope='layer_norm') :
    return tf.keras.layers.LayerNormalization(epsilon=1e-12, 
                                              center=True, 
                                              scale=True)(x)
#     return tf.contrib.layers.layer_norm(x,
#                                         center=True, scale=True,
#                                         scope=scope)

##################################################################################
# Loss function
##################################################################################

"""

Author use LSGAN
For LSGAN, multiply each of G and D by 0.5.
However, MUNIT authors did not do this.

"""

def discriminator_loss(type, real, fake):
    n_scale = len(real)
    loss = []

    real_loss = 0
    fake_loss = 0

    for i in range(n_scale) :
        if type == 'lsgan' :
            real_loss = tf.reduce_mean(input_tensor=tf.math.squared_difference(real[i], 1.0))
            fake_loss = tf.reduce_mean(input_tensor=tf.square(fake[i]))

        if type == 'gan' :
            real_loss = tf.reduce_mean(input_tensor=tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(real[i]), logits=real[i]))
            fake_loss = tf.reduce_mean(input_tensor=tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.zeros_like(fake[i]), logits=fake[i]))

        loss.append(real_loss + fake_loss)

    return sum(loss)


def generator_loss(type, fake):
    n_scale = len(fake)
    loss = []

    fake_loss = 0

    for i in range(n_scale) :
        if type == 'lsgan' :
            fake_loss = tf.reduce_mean(input_tensor=tf.math.squared_difference(fake[i], 1.0))

        if type == 'gan' :
            fake_loss = tf.reduce_mean(input_tensor=tf.nn.sigmoid_cross_entropy_with_logits(labels=tf.ones_like(fake[i]), logits=fake[i]))

        loss.append(fake_loss)


    return sum(loss)


def L1_loss(x, y):
    loss = tf.reduce_mean(input_tensor=tf.abs(x - y))

    return loss

def regularization_loss(scope_name) :
    """
    If you want to use "Regularization"
    g_loss += regularization_loss('generator')
    d_loss += regularization_loss('discriminator')
    """
    collection_regularization = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.REGULARIZATION_LOSSES)

    loss = []
    for item in collection_regularization :
        if scope_name in item.name :
            loss.append(item)

    return tf.reduce_sum(input_tensor=loss)