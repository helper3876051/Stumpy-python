# STUMPY
# Copyright 2019 TD Ameritrade. Released under the terms of the 3-Clause BSD license.
# STUMPY is a trademark of TD Ameritrade IP Company, Inc. All rights reserved.

import logging

import numpy as np
from numba import njit
import numba

from . import core, config
from .aamp import _aamp

logger = logging.getLogger(__name__)


@njit(
    "(f8[:], f8[:], i8, b1[:], b1[:], f8[:], f8[:], f8[:], i8, i8, f8[:], f8[:], i8[:],"
    "optional(i8))",
    parallel=True,
    fastmath=True,
)
def _prescraamp(
    T_A,
    T_B,
    m,
    T_A_subseq_isfinite,
    T_B_subseq_isfinite,
    T_A_squared,
    T_B_squared,
    QT,
    i,
    s,
    squared_distance_profile,
    P_squared,
    I,
    excl_zone=None,
):
    """
    A Numba JIT-compiled implementation of the non-normalized (i.e., without
    z-normalization) preSCRIMP algorithm.

    Parameters
    ----------
    T_A : numpy.ndarray
        The time series or sequence for which to compute the matrix profile

    T_B : numpy.ndarray
        The time series or sequence that will be used to annotate T_A. For every
        subsequence in T_A, its nearest neighbor in T_B will be recorded.

    m : int
        Window size

    T_A_subseq_isfinite : numpy.ndarray
        A boolean array that indicates whether a subsequence in `T_A` contains a
        `np.nan`/`np.inf` value (False)

    T_B_subseq_isfinite : numpy.ndarray
        A boolean array that indicates whether a subsequence in `T_B` contains a
        `np.nan`/`np.inf` value (False)

    T_A_squared : numpy.ndarray
        Rolling window `T_A_squared`

    T_B_squared : numpy.ndarray
        Rolling window `T_B_squared`

    QT : numpy.ndarray
        Sliding dot product between `Q` in `T_B` and `T_A`

    i : int
        The subsequence index in `T_B` that corresponds to `Q`

    s : int
        The sampling interval that defaults to
        `int(np.ceil(m / config.STUMPY_EXCL_ZONE_DENOM))`

    squared_distance_profile : numpy.ndarray
        A reusable array to store the computed squared distance profile

    P_squared : numpy.ndarray
        The squared matrix profile

    I : numpy.ndarray
        The matrix profile indices

    excl_zone : int
        The half width for the exclusion zone relative to the `i`.

    Notes
    -----
    `DOI: 10.1109/ICDM.2018.00099 \
    <https://www.cs.ucr.edu/~eamonn/SCRIMP_ICDM_camera_ready_updated.pdf>`__

    See Algorithm 2
    """
    l = QT.shape[0]
    # Update P[i] relative to all T[j : j + m]
    if not T_A_subseq_isfinite[i]:  # pragma: no cover
        squared_distance_profile[:] = np.inf
    else:
        squared_distance_profile[:] = core._mass_absolute(
            T_A_squared[i], T_B_squared, QT
        )
        squared_distance_profile[:] = np.square(squared_distance_profile)
        squared_distance_profile[
            squared_distance_profile < config.STUMPY_D_SQUARED_THRESHOLD
        ] = 0.0
        squared_distance_profile[~T_B_subseq_isfinite] = np.inf
    if excl_zone is not None:
        zone_start = max(0, i - excl_zone)
        zone_stop = min(l, i + excl_zone)
        squared_distance_profile[zone_start : zone_stop + 1] = np.inf
    I[i] = np.argmin(squared_distance_profile)
    P_squared[i] = squared_distance_profile[I[i]]
    if P_squared[i] == np.inf:  # pragma: no cover
        I[i] = -1
    else:
        j = I[i]
        # Given the squared distance, work backwards and compute QT
        QT_j = (P_squared[i] - T_A_squared[i] - T_B_squared[j]) / -2.0
        QT_j_prime = QT_j
        for k in range(1, min(s, l - max(i, j))):
            QT_j = (
                QT_j
                - T_B[i + k - 1] * T_A[j + k - 1]
                + T_B[i + k + m - 1] * T_A[j + k + m - 1]
            )
            if (
                not T_A_subseq_isfinite[i + k] or not T_B_subseq_isfinite[j + k]
            ):  # pragma: no cover
                D_squared = np.inf
            else:
                D_squared = T_A_squared[i + k] + T_B_squared[j + k] - 2 * QT_j
                if D_squared < config.STUMPY_D_SQUARED_THRESHOLD:  # pragma: no cover
                    D_squared = 0.0
            if D_squared < P_squared[i + k]:
                P_squared[i + k] = D_squared
                I[i + k] = j + k
            if D_squared < P_squared[j + k]:
                P_squared[j + k] = D_squared
                I[j + k] = i + k
        QT_j = QT_j_prime
        for k in range(1, min(s, i + 1, j + 1)):
            QT_j = QT_j - T_B[i - k + m] * T_A[j - k + m] + T_B[i - k] * T_A[j - k]
            if (
                not T_A_subseq_isfinite[i - k] or not T_B_subseq_isfinite[j - k]
            ):  # pragma: no cover
                D_squared = np.inf
            else:
                D_squared = T_A_squared[i - k] + T_B_squared[j - k] - 2 * QT_j
                if D_squared < config.STUMPY_D_SQUARED_THRESHOLD:  # pragma: no cover
                    D_squared = 0.0
            if D_squared < P_squared[i - k]:
                P_squared[i - k] = D_squared
                I[i - k] = j - k
            if D_squared < P_squared[j - k]:
                P_squared[j - k] = D_squared
                I[j - k] = i - k

    return


def prescraamp(T_A, m, T_B=None, s=None):
    """
    A convenience wrapper around the Numba JIT-compiled parallelized `_prescraamp`
    function which computes the approximate matrix profile according to the
    non-normalized (i.e., without z-normalization) preSCRIMP algorithm

    Parameters
    ----------
    T_A : numpy.ndarray
        The time series or sequence for which to compute the matrix profile

    m : int
        Window size

    T_B : numpy.ndarray, default None
        The time series or sequence that will be used to annotate T_A. For every
        subsequence in T_A, its nearest neighbor in T_B will be recorded.

    s : int, default None
        The sampling interval that defaults to
        `int(np.ceil(m / config.STUMPY_EXCL_ZONE_DENOM))`

    Returns
    -------
    P : numpy.ndarray
        Matrix profile

    I : numpy.ndarray
        Matrix profile indices

    Notes
    -----
    `DOI: 10.1109/ICDM.2018.00099 \
    <https://www.cs.ucr.edu/~eamonn/SCRIMP_ICDM_camera_ready_updated.pdf>`__

    See Algorithm 2
    """
    T_A = T_A.copy()
    T_A = np.asarray(T_A)
    core.check_dtype(T_A)
    T_A[np.isinf(T_A)] = np.nan

    if T_B is None:
        T_B = T_A
        excl_zone = int(np.ceil(m / config.STUMPY_EXCL_ZONE_DENOM))
    else:
        excl_zone = None

    T_B = T_B.copy()
    T_B = np.asarray(T_B)
    core.check_dtype(T_B)
    T_B[np.isinf(T_B)] = np.nan

    core.check_window_size(m, max_size=min(T_A.shape[0], T_B.shape[0]))

    T_A, T_A_subseq_isfinite = core.preprocess_non_normalized(T_A, m)
    T_B, T_B_subseq_isfinite = core.preprocess_non_normalized(T_B, m)

    n_A = T_A.shape[0]
    n_B = T_B.shape[0]
    l = n_A - m + 1
    P_squared = np.full(l, np.inf)
    I = np.full(l, -1, dtype=np.int64)
    squared_distance_profile = np.empty(n_B - m + 1)
    T_A_squared = np.sum(core.rolling_window(T_A * T_A, m), axis=1)
    T_B_squared = np.sum(core.rolling_window(T_B * T_B, m), axis=1)

    if s is None:  # pragma: no cover
        s = excl_zone

    for i in np.random.permutation(range(0, l, s)):
        QT = core.sliding_dot_product(T_A[i : i + m], T_B)
        _prescraamp(
            T_A,
            T_B,
            m,
            T_A_subseq_isfinite,
            T_B_subseq_isfinite,
            T_A_squared,
            T_B_squared,
            QT,
            i,
            s,
            squared_distance_profile,
            P_squared,
            I,
            excl_zone,
        )

    P = np.sqrt(P_squared)

    return P, I


class scraamp:
    """
    Compute an approximate non-normalized (i.e., without z-normalization) matrix profile

    This is a convenience wrapper around the Numba JIT-compiled parallelized
    `_aamp` function which computes the non-normalized (i.e., without z-normalization)
    matrix profile according to SCRIMP.

    Parameters
    ----------
    T_A : numpy.ndarray
        The time series or sequence for which to compute the matrix profile

    T_B : numpy.ndarray
        The time series or sequence that will be used to annotate T_A. For every
        subsequence in T_A, its nearest neighbor in T_B will be recorded.

    m : int
        Window size

    ignore_trivial : bool
        Set to `True` if this is a self-join. Otherwise, for AB-join, set this to
        `False`. Default is `True`.

    percentage : float
        Approximate percentage completed. The value is between 0.0 and 1.0.

    pre_scraamp : bool
        A flag for whether or not to perform the PreSCRIMP calculation prior to
        computing SCRIMP. If set to `True`, this is equivalent to computing
        SCRIMP++ and may lead to faster convergence

    s : int
        The size of the PreSCRIMP fixed interval. If `pre_scraamp=True` and `s=None`,
        then `s` will automatically be set to
        `s=int(np.ceil(m / config.STUMPY_EXCL_ZONE_DENOM))`, the size of the exclusion
        zone.

    Attributes
    ----------
    P_ : numpy.ndarray
        The updated matrix profile

    I_ : numpy.ndarray
        The updated matrix profile indices

    Methods
    -------
    update()
        Update the matrix profile and the matrix profile indices by computing
        additional new distances (limited by `percentage`) that make up the full
        distance matrix.

    Notes
    -----
    `DOI: 10.1109/ICDM.2018.00099 \
    <https://www.cs.ucr.edu/~eamonn/SCRIMP_ICDM_camera_ready_updated.pdf>`__

    See Algorithm 1 and Algorithm 2
    """

    def __init__(
        self,
        T_A,
        m,
        T_B=None,
        ignore_trivial=True,
        percentage=0.01,
        pre_scraamp=False,
        s=None,
    ):
        """
        Initialize the `scraamp` object

        Parameters
        ----------
        T_A : numpy.ndarray
            The time series or sequence for which to compute the matrix profile

        m : int
            Window size

        T_B : numpy.ndarray, default None
            The time series or sequence that will be used to annotate T_A. For every
            subsequence in T_A, its nearest neighbor in T_B will be recorded.

        ignore_trivial : bool, default True
            Set to `True` if this is a self-join. Otherwise, for AB-join, set this to
            `False`. Default is `True`.

        percentage : float, default 0.01
            Approximate percentage completed. The value is between 0.0 and 1.0.

        pre_scraamp : bool, default False
            A flag for whether or not to perform the PreSCRIMP calculation prior to
            computing SCRIMP. If set to `True`, this is equivalent to computing
            SCRIMP++

        s : int, default None
            The size of the PreSCRIMP fixed interval. If `pre_scraamp=True` and
            `s=None`, then `s` will automatically be set to
            `s=int(np.ceil(m / config.STUMPY_EXCL_ZONE_DENOM))`, the
            size of the exclusion zone.
        """
        self._ignore_trivial = ignore_trivial

        if T_B is None:
            T_B = T_A
            self._ignore_trivial = True

        self._m = m

        self._T_A, self._T_A_subseq_isfinite = core.preprocess_non_normalized(
            T_A, self._m
        )
        self._T_B, self._T_B_subseq_isfinite = core.preprocess_non_normalized(
            T_B, self._m
        )

        if self._T_A.ndim != 1:  # pragma: no cover
            raise ValueError(
                f"T_A is {self._T_A.ndim}-dimensional and must be 1-dimensional. "
                "For multidimensional STUMP use `stumpy.mstump` or `stumpy.mstumped`"
            )

        if self._T_B.ndim != 1:  # pragma: no cover
            raise ValueError(
                f"T_B is {self._T_B.ndim}-dimensional and must be 1-dimensional. "
                "For multidimensional STUMP use `stumpy.mstump` or `stumpy.mstumped`"
            )

        core.check_window_size(m, max_size=min(T_A.shape[0], T_B.shape[0]))

        if self._ignore_trivial is False and core.are_arrays_equal(
            self._T_A, self._T_B
        ):  # pragma: no cover
            logger.warning("Arrays T_A, T_B are equal, which implies a self-join.")
            logger.warning("Try setting `ignore_trivial = True`.")

        if (
            self._ignore_trivial
            and core.are_arrays_equal(self._T_A, self._T_B) is False
        ):  # pragma: no cover
            logger.warning("Arrays T_A, T_B are not equal, which implies an AB-join.")
            logger.warning("Try setting `ignore_trivial = False`.")

        self._n_A = self._T_A.shape[0]
        self._n_B = self._T_B.shape[0]
        self._l = self._n_A - self._m + 1

        self._P = np.empty((self._l, 3), dtype=np.float64)
        self._I = np.empty((self._l, 3), dtype=np.int64)
        self._P[:, :] = np.inf
        self._I[:, :] = -1

        self._excl_zone = int(np.ceil(self._m / config.STUMPY_EXCL_ZONE_DENOM))

        if s is None:
            s = self._excl_zone

        if pre_scraamp:
            if self._ignore_trivial:
                P, I = prescraamp(T_A, m, s=s)
            else:
                P, I = prescraamp(T_A, m, T_B=T_B, s=s)
            for i in range(P.shape[0]):
                if self._P[i, 0] > P[i]:
                    self._P[i, 0] = P[i]
                    self._I[i, 0] = I[i]

        if self._ignore_trivial:
            self._diags = np.random.permutation(
                range(self._excl_zone + 1, self._n_A - self._m + 1)
            ).astype(np.int64)
            if self._diags.shape[0] == 0:  # pragma: no cover
                max_m = core.get_max_window_size(self._T_A.shape[0])
                raise ValueError(
                    f"The window size, `m = {self._m}`, is too long for a self join. "
                    f"Please try a value of `m <= {max_m}`"
                )
        else:
            self._diags = np.random.permutation(
                range(-(self._n_A - self._m + 1) + 1, self._n_B - self._m + 1)
            ).astype(np.int64)

        self._n_threads = numba.config.NUMBA_NUM_THREADS
        self._percentage = np.clip(percentage, 0.0, 1.0)
        self._n_chunks = int(np.ceil(1.0 / percentage))
        self._ndist_counts = core._count_diagonal_ndist(
            self._diags, self._m, self._n_A, self._n_B
        )
        self._chunk_diags_ranges = core._get_array_ranges(
            self._ndist_counts, self._n_chunks, True
        )
        self._n_chunks = self._chunk_diags_ranges.shape[0]
        self._chunk_idx = 0

    def update(self):
        """
        Update the matrix profile and the matrix profile indices by computing
        additional new distances (limited by `percentage`) that make up the full
        distance matrix.
        """
        if self._chunk_idx < self._n_chunks:
            start_idx, stop_idx = self._chunk_diags_ranges[self._chunk_idx]

            P, I = _aamp(
                self._T_A,
                self._T_B,
                self._m,
                self._T_A_subseq_isfinite,
                self._T_B_subseq_isfinite,
                self._diags[start_idx:stop_idx],
                self._ignore_trivial,
            )

            # Update matrix profile and indices
            for i in range(self._P.shape[0]):
                if self._P[i, 0] > P[i, 0]:
                    self._P[i, 0] = P[i, 0]
                    self._I[i, 0] = I[i, 0]
                # left matrix profile and left matrix profile indices
                if self._P[i, 1] > P[i, 1]:
                    self._P[i, 1] = P[i, 1]
                    self._I[i, 1] = I[i, 1]
                # right matrix profile and right matrix profile indices
                if self._P[i, 2] > P[i, 2]:
                    self._P[i, 2] = P[i, 2]
                    self._I[i, 2] = I[i, 2]

            self._chunk_idx += 1

    @property
    def P_(self):
        """
        Get the updated matrix profile
        """
        return self._P[:, 0].astype(np.float64)

    @property
    def I_(self):
        """
        Get the updated matrix profile indices
        """
        return self._I[:, 0].astype(np.int64)

    @property
    def left_I_(self):
        """
        Get the updated left matrix profile indices
        """
        return self._I[:, 1].astype(np.int64)

    @property
    def right_I_(self):
        """
        Get the updated right matrix profile indices
        """
        return self._I[:, 2].astype(np.int64)
