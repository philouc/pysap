##########################################################################
# XXX - Copyright (C) XXX, 2017
# Distributed under the terms of the CeCILL-B license, as published by
# the CEA-CNRS-INRIA. Refer to the LICENSE file or to
# http://www.cecill.info/licences/Licence_CeCILL-B_V1-en.html
# for details.
##########################################################################

"""
FISTA or CONDAT-VU MRI reconstruction.
"""


# System import
from __future__ import print_function
import copy
import time

# Package import
from pisap.plugins.mri.reconstruct.cost import DualGapCost
from pisap.plugins.mri.reconstruct.reweight import mReweight
from pisap.plugins.mri.reconstruct.utils import condatvu_logo

# Third party import
import numpy as np
from sf_tools.math.stats import sigma_mad
from sf_tools.signal.linear import Identity
from sf_tools.signal.proximity import Positive
from .proximity import Threshold
from sf_tools.signal.optimisation import Condat
from sf_tools.signal.reweight import cwbReweight
from sf_tools.signal.optimisation import ForwardBackward


def sparse_rec_condatvu(gradient_op, linear_op, std_est=None,
                        std_est_method=None, std_thr=2.,
                        mu=1e-6, tau=None, sigma=None, relaxation_factor=1.0,
                        nb_of_reweights=1, max_nb_of_iter=150,
                        add_positivity=False, atol=1e-4, verbose=0):
    """ The Condat-Vu sparse reconstruction with reweightings.
    .. note:: At the moment, supports only 2D data.
    Parameters
    ----------
    data: ndarray
        the data to reconstruct: observation are expected in Fourier space.
    wavelet_name: str
        the wavelet name to be used during the decomposition.
    nb_scales: int, default 4
        the number of scales in the wavelet decomposition.
    std_est: float, default None
        the noise std estimate.
        If None use the MAD as a consistent estimator for the std.
    std_est_method: str, default None
        if the standard deviation is not set, estimate this parameter using
        the mad routine in the image ('primal') or in the sparse wavelet
        decomposition ('dual') domain.
    std_thr: float, default 2.
        use this treshold expressed as a number of sigma in the residual
        proximity operator during the thresholding.
    mu: float, default 1e-6
        regularization hyperparameter.
    tau, sigma: float, default None
        parameters of the Condat-Vu proximal-dual splitting algorithm.
        If None estimates these parameters.
    relaxation_factor: float, default 0.5
        parameter of the Condat-Vu proximal-dual splitting algorithm.
        If 1, no relaxation.
    nb_of_reweights: int, default 1
        the number of reweightings.
    max_nb_of_iter: int, default 150
        the maximum number of iterations in the Condat-Vu proximal-dual
        splitting algorithm.
    add_positivity: bool, default False
        by setting this option, set the proximity operator to identity or
        positive.
    atol: float, default 1e-4
        tolerance threshold for convergence.
    verbose: int, default 0
        the verbosity level.
    Returns
    -------
    x_final: ndarray
        the estimated CONDAT-VU solution.
    transform: a WaveletTransformBase derived instance
        the wavelet transformation instance.
    """
    # Check inputs
    # analysis = True
    # if hasattr(gradient_op, 'linear_op'):
    #     analysis = False

    if verbose > 0:
        print(condatvu_logo())

    start = time.clock()

    if std_est_method not in (None, "primal", "dual"):
        raise ValueError(
            "Unrecognize std estimation method '{0}'.".format(std_est_method))

    # Define the initial primal and dual solutions
    x_init = np.zeros(gradient_op.fourier_op.shape, dtype=np.complex)
    weights = linear_op.op(x_init)

    # Define the weights used during the thresholding in the dual domain,
    # the reweighting strategy, and the prox dual operator

    # Case1: estimate the noise std in the image domain
    if std_est_method == "primal":
        if std_est is None:
            std_est = sigma_mad(gradient_op.MtX(gradient_op.y))
        weights[...] = std_thr * std_est
        reweight_op = cwbReweight(weights)
        prox_dual_op = Threshold(reweight_op.weights)

    # Case2: estimate the noise std in the sparse wavelet domain
    elif std_est_method == "dual":
        if std_est is None:
            std_est = 0.0
        weights[...] = std_thr * std_est
        reweight_op = mReweight(weights, linear_op, thresh_factor=std_thr)
        prox_dual_op = Threshold(reweight_op.weights)

    # Case3: manual regularization mode, no reweighting
    else:
        weights[...] = mu
        reweight_op = None
        prox_dual_op = Threshold(weights)
        nb_of_reweights = 0

    # Define the Condat Vu optimizer: define the tau and sigma in the
    # Condat-Vu proximal-dual splitting algorithm if not already provided.
    # Check also that the combination of values will lead to convergence.
    norm = linear_op.l2norm(gradient_op.fourier_op.shape)
    lipschitz_cst = gradient_op.spec_rad
    if sigma is None:
        sigma = 0.5
    if tau is None:
        # to avoid numerics troubles with the convergence bound
        eps = 1.0e-8
        # due to the convergence bound
        tau = 1.0 / (lipschitz_cst/2 + sigma * norm**2 + eps)
    convergence_test = (
        1.0 / tau - sigma * norm ** 2 >= lipschitz_cst / 2.0)

    # Define initial primal and dual solutions
    primal = np.zeros(gradient_op.fourier_op.shape, dtype=np.complex)
    dual = linear_op.op(primal)
    dual[...] = 0.0

    # Welcome message
    if verbose > 0:
        print(" - mu: ", mu)
        print(" - lipschitz constant: ", gradient_op.spec_rad)
        print(" - tau: ", tau)
        print(" - sigma: ", sigma)
        print(" - rho: ", relaxation_factor)
        print(" - std: ", std_est)
        print(" - 1/tau - sigma||L||^2 >= beta/2: ", convergence_test)
        print(" - data: ", gradient_op.y.shape)
        print(" - max iterations: ", max_nb_of_iter)
        print(" - number of reweights: ", nb_of_reweights)
        print(" - primal variable shape: ", primal.shape)
        print(" - dual variable shape: ", dual.shape)
        print("-" * 40)

    # Define the proximity operator
    if add_positivity:
        prox_op = Positive()
    else:
        prox_op = Identity()

    # Define the cost function
    cost_op = DualGapCost(
        linear_op=linear_op,
        initial_cost=1e6,
        tolerance=1e-4,
        cost_interval=1,
        test_range=4,
        verbose=0,
        plot_output=None)

    # Define the optimizer
    opt = Condat(
        x=primal,
        y=dual,
        grad=gradient_op,
        prox=prox_op,
        prox_dual=prox_dual_op,
        linear=linear_op,
        cost=cost_op,
        rho=relaxation_factor,
        sigma=sigma,
        tau=tau,
        rho_update=None,
        sigma_update=None,
        tau_update=None,
        auto_iterate=False)

    # Perform the first reconstruction
    if verbose > 0:
        print("Starting optimization...")

    for i in range(max_nb_of_iter):
        opt.update()

    opt.x_final = opt.x_new
    opt.y_final = opt.y_new

    # Loop through the number of reweightings
    for reweight_index in range(nb_of_reweights):

        # Generate the new weights following reweighting prescription
        if std_est_method == "primal":
            reweight_op.reweight(linear_op.op(opt.x_new))
        else:
            std_est = reweight_op.reweight(opt.x_new)

        # Welcome message
        if verbose > 0:
            print(" - reweight: ", reweight_index + 1)
            print(" - std: ", std_est)

        # Update the weights in the dual proximity operator
        prox_dual_op.weights = reweight_op.weights

        # Perform optimisation with new weights
        opt.iterate(max_iter=max_nb_of_iter)

    # Goodbye message
    end = time.clock()
    if verbose > 0:
        print(" - final iteration number: ", cost_op._iteration)
        print(" - final cost value: ", cost_op.cost)
        print(" - converged: ", opt.converge)
        print("Done.")
        print("Execution time: ", end - start, " seconds")
        print("-" * 40)

    # Get the final solution
    x_final = opt.x_final
    linear_op.set_coeff(opt.y_final)

    return x_final, linear_op.coeff
