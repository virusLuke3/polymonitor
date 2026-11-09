"""Run the optional local model using only the private environment configuration."""
from __future__ import annotations

import ipaddress
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.environment import configured_value


def model_command() -> tuple[list[str], dict[str, str]]:
    def required(suffix: str) -> str:
        name = "POLYMONITOR_AGENT_MODEL_" + suffix
        value = configured_value(name).strip()
        if not value:
            raise ValueError(f"Missing {name}")
        return value

    host = required("HOST")
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Local model must bind to a loopback address")
    python, model = required("PYTHON"), required("PATH")
    if not Path(python).is_file() or not Path(model, "config.json").is_file():
        raise ValueError("Configured local model or interpreter is unavailable")
    name = configured_value("POLYDATA_AGENT_MODEL").strip()
    if not name:
        raise ValueError("Missing POLYDATA_AGENT_MODEL")
    command = [python, "-s", "-m", "sglang.launch_server", "--model-path", model,
               "--served-model-name", name, "--host", host, "--port", required("PORT"),
               "--mem-fraction-static", required("MEMORY_FRACTION"),
               "--context-length", required("CONTEXT"), "--max-running-requests", "1",
               "--max-queued-requests", "4", "--chunked-prefill-size", "2048", "--disable-cuda-graph",
               "--attention-backend", "triton", "--sampling-backend", "pytorch",
               "--reasoning-parser", "qwen3", "--tool-call-parser", "qwen3_coder"]
    # Do not load unrelated API keys into the model process, or have systemd
    # parse the entire personal .env (legacy aliases may not be shell identifiers).
    env = {key: value for key, value in os.environ.items()
           if key in {"HOME", "USER", "PATH", "LANG", "LC_ALL", "TMPDIR"}}
    cuda = required("CUDA_HOME")
    env["PATH"] = os.pathsep.join((str(Path(cuda) / "bin"), str(Path(python).parent), env.get("PATH", "/usr/bin:/bin")))
    env["CUDA_HOME"] = cuda
    env.update(CUDA_VISIBLE_DEVICES=required("GPU"), LD_LIBRARY_PATH=required("LIBRARY_PATH"),
               PYTHONNOUSERSITE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               TOKENIZERS_PARALLELISM="false", RAYON_NUM_THREADS="2", MAX_JOBS="2",
               TORCHINDUCTOR_COMPILE_THREADS="1")
    return command, env


if __name__ == "__main__":
    argv, environment = model_command()
    os.execve(argv[0], argv, environment)
