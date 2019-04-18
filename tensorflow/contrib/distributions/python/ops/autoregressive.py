# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""The Autoregressive distribution."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np

from tensorflow.python.framework import ops
from tensorflow.python.ops.distributions import distribution as distribution_lib
from tensorflow.python.ops.distributions import util as distribution_util
from tensorflow.python.util import deprecation


class Autoregressive(distribution_lib.Distribution):
  """Autoregressive distributions.

  The Autoregressive distribution enables learning (often) richer multivariate
  distributions by repeatedly applying a [diffeomorphic](
  https://en.wikipedia.org/wiki/Diffeomorphism) transformation (such as
  implemented by `Bijector`s). Regarding terminology,

    "Autoregressive models decompose the joint density as a product of
    conditionals, and model each conditional in turn. Normalizing flows
    transform a base density (e.g. a standard Gaussian) into the target density
    by an invertible transformation with tractable Jacobian." [(Papamakarios et
    al., 2016)][1]

  In other words, the "autoregressive property" is equivalent to the
  decomposition, `p(x) = prod{ p(x[i] | x[0:i]) : i=0, ..., d }`. The provided
  `shift_and_log_scale_fn`, `masked_autoregressive_default_template`, achieves
  this property by zeroing out weights in its `masked_dense` layers.

  Practically speaking the autoregressive property means that there exists a
  permutation of the event coordinates such that each coordinate is a
  diffeomorphic function of only preceding coordinates
  [(van den Oord et al., 2016)][2].

  #### Mathematical Details

  The probability function is

  ```none
  prob(x; fn, n) = fn(x).prob(x)
  ```

  And a sample is generated by

  ```none
  x = fn(...fn(fn(x0).sample()).sample()).sample()
  ```

  where the ellipses (`...`) represent `n-2` composed calls to `fn`, `fn`
  constructs a `tfp.distributions.Distribution`-like instance, and `x0` is a
  fixed initializing `Tensor`.

  #### Examples

  ```python
  import tensorflow_probability as tfp
  tfd = tfp.distributions

  def normal_fn(self, event_size):
    n = event_size * (event_size + 1) / 2
    p = tf.Variable(tfd.Normal(loc=0., scale=1.).sample(n))
    affine = tfd.bijectors.Affine(
        scale_tril=tfd.fill_triangular(0.25 * p))
    def _fn(samples):
      scale = math_ops.exp(affine.forward(samples)).eval()
      return independent_lib.Independent(
          normal_lib.Normal(loc=0., scale=scale, validate_args=True),
          reinterpreted_batch_ndims=1)
    return _fn

  batch_and_event_shape = [3, 2, 4]
  sample0 = array_ops.zeros(batch_and_event_shape)
  ar = autoregressive_lib.Autoregressive(
      self._normal_fn(batch_and_event_shape[-1]), sample0)
  x = ar.sample([6, 5])
  # ==> x.shape = [6, 5, 3, 2, 4]
  prob_x = ar.prob(x)
  # ==> x.shape = [6, 5, 3, 2]

  ```

  #### References

  [1]: George Papamakarios, Theo Pavlakou, and Iain Murray. Masked
       Autoregressive Flow for Density Estimation. In _Neural Information
       Processing Systems_, 2017. https://arxiv.org/abs/1705.07057

  [2]: Aaron van den Oord, Nal Kalchbrenner, Oriol Vinyals, Lasse Espeholt,
       Alex Graves, and Koray Kavukcuoglu. Conditional Image Generation with
       PixelCNN Decoders. In _Neural Information Processing Systems_, 2016.
       https://arxiv.org/abs/1606.05328
  """

  @deprecation.deprecated(
      "2018-10-01",
      "The TensorFlow Distributions library has moved to "
      "TensorFlow Probability "
      "(https://github.com/tensorflow/probability). You "
      "should update all references to use `tfp.distributions` "
      "instead of `tf.contrib.distributions`.",
      warn_once=True)
  def __init__(self,
               distribution_fn,
               sample0=None,
               num_steps=None,
               validate_args=False,
               allow_nan_stats=True,
               name="Autoregressive"):
    """Construct an `Autoregressive` distribution.

    Args:
      distribution_fn: Python `callable` which constructs a
        `tfp.distributions.Distribution`-like instance from a `Tensor` (e.g.,
        `sample0`). The function must respect the "autoregressive property",
        i.e., there exists a permutation of event such that each coordinate is a
        diffeomorphic function of on preceding coordinates.
      sample0: Initial input to `distribution_fn`; used to
        build the distribution in `__init__` which in turn specifies this
        distribution's properties, e.g., `event_shape`, `batch_shape`, `dtype`.
        If unspecified, then `distribution_fn` should be default constructable.
      num_steps: Number of times `distribution_fn` is composed from samples,
        e.g., `num_steps=2` implies
        `distribution_fn(distribution_fn(sample0).sample(n)).sample()`.
      validate_args: Python `bool`.  Whether to validate input with asserts.
        If `validate_args` is `False`, and the inputs are invalid,
        correct behavior is not guaranteed.
      allow_nan_stats: Python `bool`, default `True`. When `True`, statistics
        (e.g., mean, mode, variance) use the value "`NaN`" to indicate the
        result is undefined. When `False`, an exception is raised if one or
        more of the statistic's batch members are undefined.
      name: Python `str` name prefixed to Ops created by this class.
        Default value: "Autoregressive".

    Raises:
      ValueError: if `num_steps` and
        `distribution_fn(sample0).event_shape.num_elements()` are both `None`.
      ValueError: if `num_steps < 1`.
    """
    parameters = dict(locals())
    with ops.name_scope(name) as name:
      self._distribution_fn = distribution_fn
      self._sample0 = sample0
      self._distribution0 = (distribution_fn() if sample0 is None
                             else distribution_fn(sample0))
      if num_steps is None:
        num_steps = self._distribution0.event_shape.num_elements()
        if num_steps is None:
          raise ValueError("distribution_fn must generate a distribution "
                           "with fully known `event_shape`.")
      if num_steps < 1:
        raise ValueError("num_steps ({}) must be at least 1.".format(num_steps))
      self._num_steps = num_steps
    super(Autoregressive, self).__init__(
        dtype=self._distribution0.dtype,
        reparameterization_type=self._distribution0.reparameterization_type,
        validate_args=validate_args,
        allow_nan_stats=allow_nan_stats,
        parameters=parameters,
        graph_parents=self._distribution0._graph_parents,  # pylint: disable=protected-access
        name=name)

  @property
  def distribution_fn(self):
    return self._distribution_fn

  @property
  def sample0(self):
    return self._sample0

  @property
  def num_steps(self):
    return self._num_steps

  @property
  def distribution0(self):
    return self._distribution0

  def _batch_shape(self):
    return self.distribution0.batch_shape

  def _batch_shape_tensor(self):
    return self.distribution0.batch_shape_tensor()

  def _event_shape(self):
    return self.distribution0.event_shape

  def _event_shape_tensor(self):
    return self.distribution0.event_shape_tensor()

  def _sample_n(self, n, seed=None):
    if seed is None:
      seed = distribution_util.gen_new_seed(
          seed=np.random.randint(2**32 - 1),
          salt="autoregressive")
    samples = self.distribution0.sample(n, seed=seed)
    for _ in range(self._num_steps):
      samples = self.distribution_fn(samples).sample(seed=seed)
    return samples

  def _log_prob(self, value):
    return self.distribution_fn(value).log_prob(value)

  def _prob(self, value):
    return self.distribution_fn(value).prob(value)
