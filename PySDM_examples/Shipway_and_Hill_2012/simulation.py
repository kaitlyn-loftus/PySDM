from PySDM.environments.kinematic_1d import Kinematic1D
from PySDM.backends import CPU
from PySDM import Builder
from PySDM.dynamics import EulerianAdvection, Condensation, AmbientThermodynamics, Displacement, Coalescence
from PySDM.products import (RelativeHumidity, Pressure, Temperature,
                            WaterVapourMixingRatio, DryAirDensity, DryAirPotentialTemperature,
                            ParticlesDrySizeSpectrum, ParticlesWetSizeSpectrum, WaterMixingRatio)
from PySDM.state.mesh import Mesh
from PySDM.initialisation import spectral_sampling, spatial_sampling
from PySDM.dynamics.coalescence.kernels import Geometric
from .mpdata_1d import MPDATA_1D
import numpy as np


class Simulation:

    def __init__(self, settings, backend=CPU):
        self.nt = settings.nt

        builder = Builder(backend=backend, n_sd=settings.n_sd)
        mesh = Mesh(grid=(settings.nz,), size=(settings.z_max,))
        env = Kinematic1D(dt=settings.dt, mesh=mesh, thd_of_z=settings.thd, rhod_of_z=settings.rhod)

        mpdata = MPDATA_1D(nz=settings.nz, dt=settings.dt, mpdata_settings=settings.mpdata_settings,
                           advector_of_t=lambda t: settings.w(t) * settings.dt / settings.dz,
                           advectee_of_zZ_at_t0=lambda zZ: settings.qv(zZ*settings.dz),
                           g_factor_of_zZ=lambda zZ: settings.rhod(zZ*settings.dz))

        builder.set_environment(env)
        builder.add_dynamic(AmbientThermodynamics())
        builder.add_dynamic(Condensation(
            adaptive=settings.condensation_adaptive,
            rtol_thd=settings.condensation_rtol_thd,
            rtol_x=settings.condensation_rtol_x,
            kappa=settings.kappa
        ))
        builder.add_dynamic(EulerianAdvection(mpdata))
        if settings.precip:
            builder.add_dynamic(Coalescence(
                kernel=Geometric(collection_efficiency=1),
                adaptive=settings.coalescence_adaptive
            ))
            builder.add_dynamic(Displacement(enable_sedimentation=True, courant_field=(np.zeros(settings.nz+1),)))  # TODO
        attributes = env.init_attributes(
            spatial_discretisation=spatial_sampling.Pseudorandom(),
            spectral_discretisation=spectral_sampling.ConstantMultiplicity(
                spectrum=settings.wet_radius_spectrum_per_mass_of_dry_air
            ),
            kappa=settings.kappa
        )
        products = [
            RelativeHumidity(), Pressure(), Temperature(),
            WaterVapourMixingRatio(),
            WaterMixingRatio('ql', 'cloud', settings.cloud_water_radius_range),
            WaterMixingRatio('qr', 'rain', settings.rain_water_radius_range),
            DryAirDensity(),
            DryAirPotentialTemperature(),
            ParticlesDrySizeSpectrum(v_bins=settings.v_bin_edges),
            ParticlesWetSizeSpectrum(v_bins=settings.v_bin_edges)
        ]
        self.core = builder.build(attributes=attributes, products=products)

    def save(self, output, step):
        for k, v in self.core.products.items():
            if len(v.shape) == 1:
                output[k][:, step] = v.get()

    def run(self, nt=None):
        nt = self.nt if nt is None else nt
        mesh = self.core.mesh

        output = {k: np.zeros((mesh.grid[-1], nt+1)) for k in self.core.products.keys()}
        assert 't' not in output and 'z' not in output
        output['t'] = np.linspace(0, self.nt*self.core.dt, self.nt+1, endpoint=True)
        output['z'] = np.linspace(mesh.dz/2, (mesh.grid[-1]-1/2)*mesh.dz, mesh.grid[-1], endpoint=True)

        self.save(output, 0)
        for step in range(nt):
            self.core.run(steps=1)
            self.save(output, step+1)
        return output