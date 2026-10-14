from earthcharge.core.design import Scenario


def quick(load="phone", hours=1.0, dt=10.0, **kw) -> Scenario:
    sc = Scenario()
    sc.sim.load_mode = load
    sc.sim.duration_h = hours
    sc.sim.dt_s = dt
    sc.phone.max_time_h = hours
    for key, value in kw.items():
        obj, attr = key.split("__")
        target = {"g": sc.design.geometry, "st": sc.design.stack, "cv": sc.design.converter,
                  "sc": sc.design.supercap, "env": sc.design.environment, "ph": sc.phone, "sim": sc.sim,
                  "d": sc.design, "dist": sc.design.disturbances}[obj]
        setattr(target, attr, value)
    return sc
