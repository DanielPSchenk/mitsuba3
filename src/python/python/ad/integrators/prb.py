from __future__ import annotations # Delayed parsing of type annotations

import drjit as dr
import mitsuba as mi

from .common import RBIntegrator, mis_weight

class PRBIntegrator(RBIntegrator):
    r"""
    .. _integrator-prb:

    Path Replay Backpropagation (:monosp:`prb`)
    -------------------------------------------

    .. pluginparameters::

     * - max_depth
       - |int|
       - Specifies the longest path depth in the generated output image (where -1
         corresponds to :math:`\infty`). A value of 1 will only render directly
         visible light sources. 2 will lead to single-bounce (direct-only)
         illumination, and so on. (Default: 6)

     * - rr_depth
       - |int|
       - Specifies the path depth, at which the implementation will begin to use
         the *russian roulette* path termination criterion. For example, if set to
         1, then path generation many randomly cease after encountering directly
         visible surfaces. (Default: 5)

    This plugin implements a basic Path Replay Backpropagation (PRB) integrator
    with the following properties:

    - Emitter sampling (a.k.a. next event estimation).

    - Russian Roulette stopping criterion.

    - No reparameterization. This means that the integrator cannot be used for
      shape optimization (it will return incorrect/biased gradients for
      geometric parameters like vertex positions.)

    - Detached sampling. This means that the properties of ideal specular
      objects (e.g., the IOR of a glass vase) cannot be optimized.

    See ``prb_basic.py`` for an even more reduced implementation that removes
    the first two features.

    See the papers :cite:`Vicini2021` and :cite:`Zeltner2021MonteCarlo`
    for details on PRB, attached/detached sampling, and reparameterizations.

    .. tabs::

        .. code-tab:: python

            'type': 'prb',
            'max_depth': 8
    """

#    @dr.syntax(print_code=True)
#    def sample(self,
#               mode: dr.ADMode,
#               scene: mi.Scene,
#               sampler: mi.Sampler,
#               ray: mi.Ray3f,
#               δL: Optional[mi.Spectrum],
#               state_in: Optional[mi.Spectrum],
#               active: mi.Bool,
#               **kwargs # Absorbs unused arguments
#    ) -> Tuple[mi.Spectrum,
#               mi.Bool, mi.Spectrum]:
#        """
#        See ``ADIntegrator.sample()`` for a description of this interface and
#        the role of the various parameters and return values.
#        """
#
#        # Rendering a primal image? (vs performing forward/reverse-mode AD)
#        primal = mode == dr.ADMode.Primal
#
#        # Standard BSDF evaluation context for path tracing
#        bsdf_ctx = mi.BSDFContext()
#
#        # --------------------- Configure loop state ----------------------
#
#        # Copy input arguments to avoid mutating the caller's state
#        ray = mi.Ray3f(dr.detach(ray))
#        depth = mi.UInt32(0)                          # Depth of current vertex
#        L = mi.Spectrum(0 if primal else state_in)    # Radiance accumulator
#        δL = mi.Spectrum(δL if δL is not None else 0) # Differential/adjoint radiance
#        β = mi.Spectrum(1)                            # Path throughput weight
#        η = mi.Float(1)                               # Index of refraction
#        active = mi.Bool(active)                      # Active SIMD lanes
#
#        # Variables caching information from the previous bounce
#        prev_si         = dr.zeros(mi.SurfaceInteraction3f)
#        prev_bsdf_pdf   = mi.Float(1.0)
#        prev_bsdf_delta = mi.Bool(True)
#
#        while dr.hint(active,
#                      max_iterations=self.max_depth,
#                      label="Path Replay Backpropagation (%s)" % mode.name):
#            active_next = mi.Bool(active)
#
#            # Compute a surface interaction that tracks derivatives arising
#            # from differentiable shape parameters (position, normals, etc.)
#            # In primal mode, this is just an ordinary ray tracing operation.
#            with dr.resume_grad(when=not primal):
#                si = scene.ray_intersect(ray,
#                                         ray_flags=mi.RayFlags.All,
#                                         coherent=(depth == 0))
#
#            # Get the BSDF, potentially computes texture-space differentials
#            bsdf = si.bsdf(ray)
#
#            # ---------------------- Direct emission ----------------------
#
#            # Hide the environment emitter if necessary
#            if dr.hint(self.hide_emitters, mode='scalar'):
#                active_next &= ~((depth == 0) & ~si.is_valid())
#
#            # Compute MIS weight for emitter sample from previous bounce
#            ds = mi.DirectionSample3f(scene, si=si, ref=prev_si)
#
#            mis = mis_weight(
#                prev_bsdf_pdf,
#                scene.pdf_emitter_direction(prev_si, ds, ~prev_bsdf_delta)
#            )
#
#            with dr.resume_grad(when=not primal):
#                Le = β * mis * ds.emitter.eval(si, active_next)
#
#            # ---------------------- Emitter sampling ----------------------
#
#            # Should we continue tracing to reach one more vertex?
#            active_next &= (depth + 1 < self.max_depth) & si.is_valid()
#
#            # Is emitter sampling even possible on the current vertex?
#            active_em = active_next & mi.has_flag(bsdf.flags(), mi.BSDFFlags.Smooth)
#
#            # If so, randomly sample an emitter without derivative tracking.
#            ds, em_weight = scene.sample_emitter_direction(
#                si, sampler.next_2d(), True, active_em)
#            active_em &= (ds.pdf != 0.0)
#
#            with dr.resume_grad(when=not primal):
#                if dr.hint(not primal, mode='scalar'):
#                    # Given the detached emitter sample, *recompute* its
#                    # contribution with AD to enable light source optimization
#                    ds.d = dr.replace_grad(ds.d, dr.normalize(ds.p - si.p))
#                    em_val = scene.eval_emitter_direction(si, ds, active_em)
#                    em_weight = dr.replace_grad(em_weight, dr.select((ds.pdf != 0), em_val / ds.pdf, 0))
#                    dr.disable_grad(ds.d)
#
#                # Evaluate BSDF * cos(theta) differentiably
#                wo = si.to_local(ds.d)
#                bsdf_value_em, bsdf_pdf_em = bsdf.eval_pdf(bsdf_ctx, si, wo, active_em)
#                mis_em = dr.select(ds.delta, 1, mis_weight(ds.pdf, bsdf_pdf_em))
#                Lr_dir = β * mis_em * bsdf_value_em * em_weight
#
#            # ------------------ Detached BSDF sampling -------------------
#
#            bsdf_sample, bsdf_weight = bsdf.sample(bsdf_ctx, si,
#                                                   sampler.next_1d(),
#                                                   sampler.next_2d(),
#                                                   active_next)
#
#            # ---- Update loop variables based on current interaction -----
#
#            L = (L + Le + Lr_dir) if primal else (L - Le - Lr_dir)
#            ray = si.spawn_ray(si.to_world(bsdf_sample.wo))
#            η *= bsdf_sample.eta
#            β *= bsdf_weight
#
#            # Information about the current vertex needed by the next iteration
#
#            prev_si = dr.detach(si, True)
#            prev_bsdf_pdf = bsdf_sample.pdf
#            prev_bsdf_delta = mi.has_flag(bsdf_sample.sampled_type, mi.BSDFFlags.Delta)
#
#            # -------------------- Stopping criterion ---------------------
#
#            # Don't run another iteration if the throughput has reached zero
#            β_max = dr.max(β)
#            active_next &= (β_max != 0)
#
#            # Russian roulette stopping probability (must cancel out ior^2
#            # to obtain unitless throughput, enforces a minimum probability)
#            rr_prob = dr.minimum(β_max * η**2, .95)
#
#            # Apply only further along the path since, this introduces variance
#            rr_active = depth >= self.rr_depth
#            β[rr_active] *= dr.rcp(rr_prob)
#            rr_continue = sampler.next_1d() < rr_prob
#            active_next &= ~rr_active | rr_continue
#
#            # ------------------ Differential phase only ------------------
#
#            if dr.hint(not primal, mode='scalar'):
#                with dr.resume_grad():
#                    # 'L' stores the indirectly reflected radiance at the
#                    # current vertex but does not track parameter derivatives.
#                    # The following addresses this by canceling the detached
#                    # BSDF value and replacing it with an equivalent term that
#                    # has derivative tracking enabled. (nit picking: the
#                    # direct/indirect terminology isn't 100% accurate here,
#                    # since there may be a direct component that is weighted
#                    # via multiple importance sampling)
#
#                    # Recompute 'wo' to propagate derivatives to cosine term
#                    wo = si.to_local(ray.d)
#
#                    # Re-evaluate BSDF * cos(theta) differentiably
#                    bsdf_val = bsdf.eval(bsdf_ctx, si, wo, active_next)
#
#                    # Detached version of the above term and inverse
#                    bsdf_val_det = bsdf_weight * bsdf_sample.pdf
#                    inv_bsdf_val_det = dr.select(bsdf_val_det != 0,
#                                                 dr.rcp(bsdf_val_det), 0)
#
#                    # Differentiable version of the reflected indirect
#                    # radiance. Minor optional tweak: indicate that the primal
#                    # value of the second term is always 1.
#                    tmp = inv_bsdf_val_det * bsdf_val
#                    tmp_replaced = dr.replace_grad(dr.ones(mi.Float, dr.width(tmp)), tmp) #FIXME
#                    Lr_ind = L * tmp_replaced
#
#                    # Differentiable Monte Carlo estimate of all contributions
#                    Lo = Le + Lr_dir + Lr_ind
#
#                    attached_contrib = dr.flag(dr.JitFlag.VCallRecord) and not dr.grad_enabled(Lo)
#                    if dr.hint(attached_contrib, mode='scalar'):
#                        raise Exception(
#                            "The contribution computed by the differential "
#                            "rendering phase is not attached to the AD graph! "
#                            "Raising an exception since this is usually "
#                            "indicative of a bug (for example, you may have "
#                            "forgotten to call dr.enable_grad(..) on one of "
#                            "the scene parameters, or you may be trying to "
#                            "optimize a parameter that does not generate "
#                            "derivatives in detached PRB.)")
#
#                    # Propagate derivatives from/to 'Lo' based on 'mode'
#                    if dr.hint(mode == dr.ADMode.Backward, mode='scalar'):
#                        dr.backward_from(δL * Lo)
#                    else:
#                        δL += dr.forward_to(Lo)
#
#            depth[si.is_valid()] += 1
#            active = active_next
#
#        return (
#            L if primal else δL, # Radiance/differential radiance
#            (depth != 0),        # Ray validity flag for alpha blending
#            L                    # State for the differential phase
#        )
    def sample(self, mode: dr.ADMode, scene: mi.Scene, sampler: mi.Sampler, ray: mi.Ray3f, δL: Optional[mi.Spectrum], state_in: Optional[mi.Spectrum], active: mi.Bool, **kwargs) -> Tuple[mi.Spectrum, mi.Bool, mi.Spectrum]:
        """
        See ``ADIntegrator.sample()`` for a description of this interface and
        the role of the various parameters and return values.
        """
        primal = mode == dr.ADMode.Primal
        bsdf_ctx = mi.BSDFContext()
        ray = mi.Ray3f(dr.detach(ray))
        depth = mi.UInt32(0)
        L = mi.Spectrum(0 if primal else state_in)
        δL = mi.Spectrum(δL if δL is not None else 0)
        β = mi.Spectrum(1)
        η = mi.Float(1)
        active = mi.Bool(active)
        prev_si = dr.zeros(mi.SurfaceInteraction3f)
        prev_bsdf_pdf = mi.Float(1.0)
        prev_bsdf_delta = mi.Bool(True)
        '-------- loop transformed by dr.syntax --------'
    
        def _loop_cond(L, active, bsdf_ctx, depth, prev_bsdf_delta, prev_bsdf_pdf, prev_si, primal, ray, sampler, scene, self, β, δL, η):
            return active
    
        def _loop_body(L, active, bsdf_ctx, depth, prev_bsdf_delta, prev_bsdf_pdf, prev_si, primal, ray, sampler, scene, self, β, δL, η):
            nonlocal mode
            active_next = mi.Bool(active)
            with dr.resume_grad(when=not primal):
                si = scene.ray_intersect(ray, ray_flags=mi.RayFlags.All, coherent=depth == 0)
            bsdf = si.bsdf(ray)
            if self.hide_emitters:
                active_next &= ~((depth == 0) & ~si.is_valid())
            ds = mi.DirectionSample3f(scene, si=si, ref=prev_si)
            mis = mis_weight(prev_bsdf_pdf, scene.pdf_emitter_direction(prev_si, ds, ~prev_bsdf_delta))
            with dr.resume_grad(when=not primal):
                Le = β * mis * ds.emitter.eval(si, active_next)
            active_next &= (depth + 1 < self.max_depth) & si.is_valid()
            active_em = active_next & mi.has_flag(bsdf.flags(), mi.BSDFFlags.Smooth)
            (ds, em_weight) = scene.sample_emitter_direction(si, sampler.next_2d(), True, active_em)
            active_em &= ds.pdf != 0.0
            with dr.resume_grad(when=not primal):
                if not primal:
                    ds.d = dr.replace_grad(ds.d, dr.normalize(ds.p - si.p))
                    em_val = scene.eval_emitter_direction(si, ds, active_em)
                    em_weight = dr.replace_grad(em_weight, dr.select(ds.pdf != 0, em_val / ds.pdf, 0))
                    dr.disable_grad(ds.d)
                wo = si.to_local(ds.d)
                (bsdf_value_em, bsdf_pdf_em) = bsdf.eval_pdf(bsdf_ctx, si, wo, active_em)
                mis_em = dr.select(ds.delta, 1, mis_weight(ds.pdf, bsdf_pdf_em))
                Lr_dir = β * mis_em * bsdf_value_em * em_weight
            (bsdf_sample, bsdf_weight) = bsdf.sample(bsdf_ctx, si, sampler.next_1d(), sampler.next_2d(), active_next)
            L = L + Le + Lr_dir if primal else L - Le - Lr_dir
            ray = si.spawn_ray(si.to_world(bsdf_sample.wo))
            η *= bsdf_sample.eta
            β *= bsdf_weight
            prev_si = dr.detach(si, True)
            prev_bsdf_pdf = bsdf_sample.pdf
            prev_bsdf_delta = mi.has_flag(bsdf_sample.sampled_type, mi.BSDFFlags.Delta)
            β_max = dr.max(β)
            active_next &= β_max != 0
            rr_prob = dr.minimum(β_max * η ** 2, 0.95)
            rr_active = depth >= self.rr_depth
            #print(f"rr_active:\t{rr_active}")
            #print(f"rcp(rr_prob):\t{dr.rcp(rr_prob)}")

            β[rr_active] *= dr.rcp(rr_prob)

            rr_continue = sampler.next_1d() < rr_prob
            active_next &= ~rr_active | rr_continue
            if not primal:
                with dr.resume_grad():
                    wo = si.to_local(ray.d)
                    bsdf_val = bsdf.eval(bsdf_ctx, si, wo, active_next)
                    bsdf_val_det = bsdf_weight * bsdf_sample.pdf
                    inv_bsdf_val_det = dr.select(bsdf_val_det != 0, dr.rcp(bsdf_val_det), 0)
                    tmp = inv_bsdf_val_det * bsdf_val
                    tmp_replaced = dr.replace_grad(dr.ones(mi.Float, dr.width(tmp)), tmp)
                    Lr_ind = L * tmp_replaced
                    Lo = Le + Lr_dir + Lr_ind
                    attached_contrib = dr.flag(dr.JitFlag.VCallRecord) and (not dr.grad_enabled(Lo))
                    if attached_contrib:
                        raise Exception('The contribution computed by the differential rendering phase is not attached to the AD graph! Raising an exception since this is usually indicative of a bug (for example, you may have forgotten to call dr.enable_grad(..) on one of the scene parameters, or you may be trying to optimize a parameter that does not generate derivatives in detached PRB.)')
                    if mode == dr.ADMode.Backward:
                        dr.backward_from(δL * Lo)
                    else:
                        δL += dr.forward_to(Lo)
            depth[si.is_valid()] += 1
            active = active_next
            return (L, active, bsdf_ctx, depth, prev_bsdf_delta, prev_bsdf_pdf, prev_si, primal, ray, sampler, scene, self, β, δL, η)
        '----------- invoke dr.while_loop --------------'
        from drjit import while_loop as _loop
        (L, active, bsdf_ctx, depth, prev_bsdf_delta, prev_bsdf_pdf, prev_si, primal, ray, sampler, scene, self, β, δL, η) = _loop((L, active, bsdf_ctx, depth, prev_bsdf_delta, prev_bsdf_pdf, prev_si, primal, ray, sampler, scene, self, β, δL, η), _loop_cond, _loop_body, labels=('L', 'active', 'bsdf_ctx', 'depth', 'prev_bsdf_delta', 'prev_bsdf_pdf', 'prev_si', 'primal', 'ray', 'sampler', 'scene', 'self', 'β', 'δL', 'η'), max_iterations=self.max_depth, label='Path Replay Backpropagation (%s)' % mode.name)
        del _loop, _loop_cond, _loop_body
        '-----------------------------------------------'
        return (L if primal else δL, depth != 0, L)

mi.register_integrator("prb", lambda props: PRBIntegrator(props))

del RBIntegrator
