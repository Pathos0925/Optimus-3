import os, time
from minestudio.simulator import MinecraftSim

N = int(os.environ.get("BENCH_STEPS", "60"))
sim = MinecraftSim(obs_size=(128, 128), preferred_spawn_biome="forest")
obs, info = sim.reset()
noop = sim.env.noop_action()
# warmup
for _ in range(5):
    sim.step(noop)
t0 = time.time()
for _ in range(N):
    sim.step(noop)
dt = time.time() - t0
print(f"RENDER_MODE={os.environ.get('MINESTUDIO_GPU_RENDER','unset(cpu)')}  steps={N}  total={dt:.2f}s  FPS={N/dt:.2f}")
sim.close()
