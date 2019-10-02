# -*- coding: utf-8 -*-
##########################################################################
# pySAP - Copyright (C) CEA, 2017 - 2018
# Distributed under the terms of the CeCILL-B license, as published by
# the CEA-CNRS-INRIA. Refer to the LICENSE file or to
# http://www.cecill.info/licences/Licence_CeCILL-B_V1-en.html
# for details.
##########################################################################

# System import
import unittest
import os
import numpy
import sys
import time


# Package import
import pysap
import pysap.extensions.transform
import pysap.extensions.sparse2d as sp
from pysap.extensions import tools
from pysap.data import get_sample_data
from numpy.testing import assert_raises
from astropy.io import fits


class TestWarpAndBinding(unittest.TestCase):
    """ Test the analysis/synthesis of an input image using a wrapping or a
    binding strategy.
    """
    def setUp(self):
        """ Get the data from the server.
        """
        self.images = [
            get_sample_data(dataset_name="mri-slice-nifti"),
            get_sample_data(dataset_name="astro-ngc2997")
            ]
        self.deconv_images = [
            get_sample_data(dataset_name="astro-galaxy"),
            get_sample_data(dataset_name="astro-psf")
        ]
        print("[info] Image loaded for test: {0}.".format(
            [i.data.shape for i in self.images]))
        transforms_struct = pysap.wavelist(["isap-2d", "isap-3d"])
        transforms_names = (
            transforms_struct["isap-2d"] + transforms_struct["isap-3d"])
        self.transforms = [
            pysap.load_transform(name) for name in transforms_names]
        print("[info] Found {0} transformations.".format(len(self.transforms)))
        self.nb_scales = [3]  # [2, 3, 4]
        self.nb_iter = 10

    def test_wavelet_transformations(self):
        """ Test all the registered transformations.
        """
        for image_i in self.images:
            print("Process test with image '{0}'...".format(
                image_i.metadata["path"]))
            for nb_scale in self.nb_scales:
                print("- Number of scales: {0}".format(nb_scale))
                for transform in self.transforms:
                    print("    Transform: {0}".format(transform))
                    if transform.__family__ == "isap-2d":
                        transform = transform(nb_scale=nb_scale, verbose=0,
                                              padding_mode="symmetric")
                    else:
                        transform = transform(nb_scale=nb_scale, verbose=0)

                    image = numpy.copy(image_i)

                    if transform.data_dim == 3:
                        image = image[64:192, 64:192]
                        image = numpy.tile(image, (image.shape[0], 1, 1))
                        transform.data = image
                    else:
                        transform.data = image

                    self.assertFalse(transform.use_wrapping)
                    transform.info
                    transform.analysis()
                    # transform.show()
                    recim = transform.synthesis()
                    # recim.show()
                    mismatch = (1. - numpy.mean(
                        numpy.isclose(recim.data, image, atol=1e-8,
                                      rtol=1e-5)))
                    print("      mismatch = ", mismatch)
                    print("      analysis = ",
                          [band.shape for band in transform.analysis_data],
                          len(transform.analysis_data))
                    print("      bands = ", transform.nb_band_per_scale)
                    print("      synthesis = ", recim.shape)

    def test_speed(self):
        """ Test the bindings time advantages.
        """
        # With/without bindings
        for strategy, name in ((True, "Without"), (False, "With")):
            tic = time.time()
            transform = pysap.load_transform(
                "LinearWaveletTransformATrousAlgorithm")
            transform = transform(nb_scale=4, verbose=0)
            transform.use_wrapping = strategy
            transform.data = self.images[0]
            for i in range(self.nb_iter):
                transform.analysis()
                recim = transform.synthesis()
            toc = time.time()
            print("[result] {0} bindings execution time: {1}.".format(
                name, toc - tic))

    def test_accessors(self):
        """ Test all the accessors.
        """
        # With/without bindings
        for strategy, name in ((True, "without"), (False, "with")):

            # Test 3-bands undecimated transform
            nb_scale = 4
            print("[info] Test {0} bindings.".format(name))
            transform = pysap.load_transform(
                "NonOrthogonalUndecimatedTransform")
            transform = transform(nb_scale=nb_scale, verbose=0)
            transform.use_wrapping = strategy
            transform.data = self.images[0]
            transform.analysis()

            # Get with scale index only
            for scale in range(nb_scale - 1):
                band_data = transform[scale]
                self.assertEqual(len(band_data), 3)
                for band_array in band_data:
                    self.assertEqual(band_array.shape, (512, 512))
            band_array = transform[nb_scale - 1]
            self.assertEqual(band_array.shape, (512, 512))

            # Get with scale and band
            self.assertEqual(transform[0, 0].shape, (512, 512))

            # Get with scale and band as slice
            band_data = transform[2, 1:3:1]
            self.assertEqual(len(band_data), 2)
            for band_array in band_data:
                self.assertEqual(band_array.shape, (512, 512))

            # Get with scale as slice and band
            band_data = transform[1:3, 0]
            self.assertEqual(len(band_data), 2)
            for band_array in band_data:
                self.assertEqual(band_array.shape, (512, 512))

            # Modify a band on the fly
            band_array = transform[0, 0]
            band_array[:, :] = 10
            self.assertTrue(numpy.allclose(transform[0, 0], band_array))

    def test_filter_init(self):
        flt = sp.Filter()
        data = numpy.copy(self.images[0])
        flt.filter(data)
        assert(flt.data is not None)

    def test_filter_default(self):
        # filter with binding
        flt = sp.Filter()
        data = numpy.copy(self.images[1])
        flt.filter(data)
        image = 0
        # filter with wrapper
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.extensions.mr_filter(in_image, out_file)
            image = numpy.copy(pysap.io.load(out_file))
            diff = flt.data - image
            self.assertFalse(diff.all())

    # Common use cases of the filter function

    def test_filter_options_t24_n5(self):
        flt = sp.Filter(type_of_multiresolution_transform=24,
                        number_of_scales=5)
        data = numpy.copy(self.images[1])
        flt.filter(data)
        image = 0
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.extensions.mr_filter(in_image,
                                       out_file,
                                       type_of_multiresolution_transform=24,
                                       number_of_scales=5)
            image = numpy.copy(pysap.io.load(out_file))
            diff = flt.data - image
            self.assertFalse(diff.all())

    def test_filter_options_t24_n5_f6(self):
        flt = sp.Filter(type_of_filtering=6,
                        type_of_multiresolution_transform=24,
                        number_of_scales=5)
        data = numpy.copy(self.images[1])
        flt.filter(data)
        image = 0
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.extensions.mr_filter(in_image,
                                       out_file,
                                       type_of_filtering=6,
                                       type_of_multiresolution_transform=24,
                                       number_of_scales=5)
            image = numpy.copy(pysap.io.load(out_file))
            diff = flt.data - image
            self.assertFalse(diff.all())

    def test_filter_options_f2_C3_t4(self):
        flt = sp.Filter(type_of_filtering=2, coef_detection_method=3,
                        type_of_multiresolution_transform=4)
        data = numpy.copy(self.images[1])
        flt.filter(data)
        image = 0
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.extensions.mr_filter(in_image,
                                       out_file,
                                       type_of_filtering=2,
                                       coef_detection_method=3,
                                       type_of_multiresolution_transform=4)
            image = numpy.copy(pysap.io.load(out_file))
            diff = flt.data - image
            self.assertFalse(diff.all())

    def test_filter_options_f3_n5(self):
        flt = sp.Filter(type_of_filtering=3, number_of_scales=5)
        data = numpy.copy(self.images[1])
        flt.filter(data)
        image = 0
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.extensions.mr_filter(in_image,
                                       out_file,
                                       type_of_filtering=3,
                                       number_of_scales=5)
            image = numpy.copy(pysap.io.load(out_file))
            diff = flt.data - image
            self.assertFalse(diff.all())

    def test_filter_noise_valueerror(self):
        data = numpy.copy(self.images[1])
        with assert_raises(ValueError):
            flt = sp.Filter(epsilon_poisson=5, type_of_noise=2)
            flt.filter(data)
        with assert_raises(ValueError):
            flt = sp.Filter(type_of_noise=9)
            flt.filter(data)
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            pysap.io.save(data, in_image)
        with assert_raises(ValueError):
            flt = sp.Filter(rms_map=in_image, type_of_noise=6)
            flt.filter(data)

    def test_deconv_init(self):
        deconv = sp.Deconvolve()
        data = self.deconv_images[0].data
        psf = self.deconv_images[1].data
        deconv.deconvolve(data, psf)
        assert(deconv.data is not None)

    def test_deconv_default(self):
        deconv = sp.Deconvolve()
        data = self.deconv_images[0].data
        psf = self.deconv_images[1].data
        deconv.deconvolve(data, psf)
        image = 0
        # deconvolve with wrapper
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            in_psf = os.path.join(tmpdir, "in_psf.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.io.save(psf, in_psf)

            pysap.extensions.mr_deconv(in_image, in_psf, out_file)
            image = numpy.copy(pysap.io.load(out_file))
            diff = deconv.data.data - image
            self.assertFalse(diff.all())

    def test_deconv_poisson(self):
        deconv = sp.Deconvolve(type_of_noise=2)
        data = self.deconv_images[0].data
        psf = self.deconv_images[1].data
        deconv.deconvolve(data, psf)
        image = 0
        # deconvolve with wrapper
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            in_psf = os.path.join(tmpdir, "in_psf.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.io.save(psf, in_psf)

            pysap.extensions.mr_deconv(in_image, in_psf, out_file,
                                       type_of_noise=2)
            image = numpy.copy(pysap.io.load(out_file))
            diff = deconv.data.data - image
            self.assertFalse(diff.all())

    def test_deconv_d1_t20(self):
        deconv = sp.Deconvolve(type_of_deconvolution=1,
                               type_of_multiresolution_transform=20)
        data = self.deconv_images[0].data
        psf = self.deconv_images[1].data
        deconv.deconvolve(data, psf)
        image = 0
        # deconvolve with wrapper
        with pysap.TempDir(isap=True) as tmpdir:
            in_image = os.path.join(tmpdir, "in.fits")
            in_psf = os.path.join(tmpdir, "in_psf.fits")
            out_file = os.path.join(tmpdir, "out.fits")
            pysap.io.save(data, in_image)
            pysap.io.save(psf, in_psf)

            pysap.extensions.mr_deconv(in_image, in_psf, out_file,
                                       type_of_deconvolution=1,
                                       type_of_multiresolution_transform=20)
            image = numpy.copy(pysap.io.load(out_file))
            diff = deconv.data.data - image
            self.assertFalse(diff.all())


if __name__ == "__main__":
    unittest.main()
