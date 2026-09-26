"""Persistent, serial voice renderer. Park weights in RAM before acknowledging.

The caller owns the cross-process GPU slot. This module owns all VoxCPM-specific
state, including its non-module attention caches and reference features.
"""
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


class Renderer:
    def __init__(self):
        sys.path.insert(0, str(ROOT / '.tools/VoxCPM/src'))
        import torch
        from voxcpm import VoxCPM
        torch.set_num_threads(4)
        self.model = VoxCPM.from_pretrained(
            hf_model_id=str(ROOT / '.tools/tts-model/base'),
            lora_weights_path=str(ROOT / '.tools/tts-model/adapter'),
            load_denoiser=False, optimize=False, device='cuda')
        self.reference_key = None
        self.reference_cache = None

    def move(self, device):
        import torch
        model = self.model.tts_model
        model.to(device)
        # These caches are plain Python objects, not registered torch buffers.
        for lm in (model.base_lm, model.residual_lm):
            lm.kv_cache.kv_cache = lm.kv_cache.kv_cache.to(device)
        if device == 'cpu':
            # Legacy weight_norm keeps a computed weight outside parameters and
            # buffers. Moving the module alone leaves those AudioVAE weights on GPU.
            from torch.nn.utils.weight_norm import WeightNorm
            with torch.no_grad():
                for module in model.modules():
                    for hook in module._forward_pre_hooks.values():
                        if isinstance(hook, WeightNorm):
                            setattr(module, hook.name, hook.compute_weight(module))
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

    def render(self, text, reference, output):
        import numpy as np
        import soundfile as sf
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
            raise ValueError('Speech text must contain 1 to 1200 characters')
        started = time.monotonic()
        self.move('cuda')
        moved = time.monotonic()
        try:
            key = hashlib.sha256(Path(reference).read_bytes()).hexdigest()
            model = self.model.tts_model
            if key != self.reference_key:
                self.reference_cache = model.build_prompt_cache(reference_wav_path=reference)
                self.reference_key = key
            parts = []
            for sentence in re.split(r'(?<=[.!?])\s+', ' '.join(text.split())):
                while len(sentence) > 240:
                    split = sentence.rfind(' ', 0, 241)
                    if split < 1: split = 240
                    parts.append(sentence[:split]); sentence = sentence[split:].strip()
                if sentence: parts.append(sentence)
            clips = []
            for part in parts:
                # Same pinned generation recipe as VoxCPM.generate, with reusable
                # CPU reference features rather than re-encoding for each sentence.
                wav, _, _ = model.generate_with_prompt_cache(
                    target_text=part, prompt_cache=self.reference_cache, min_len=2,
                    max_len=600, inference_timesteps=6, cfg_value=2.4,
                    retry_badcase=False, retry_badcase_max_times=3,
                    retry_badcase_ratio_threshold=6.0, seed=42)
                clips.append(wav.squeeze(0).cpu().numpy())
                del wav
                clips.append(np.zeros(int(model.sample_rate * 0.15), dtype=np.float32))
            audio = np.concatenate(clips[:-1])
            if not len(audio) or not np.isfinite(audio).all():raise RuntimeError('Invalid synthesized audio')
            peak = float(np.abs(audio).max())
            if peak < 0.001:raise RuntimeError('Voice model returned silence')
            sf.write(output, audio * min(0.9 / peak, 3.0), model.sample_rate, subtype='PCM_16')
            metrics = {'transfer_seconds': moved-started, 'audio_seconds':len(audio)/model.sample_rate}
        finally:
            self.move('cpu')
        import torch
        metrics.update(render_seconds=time.monotonic()-started,
                       parked_gpu_bytes=torch.cuda.memory_allocated())
        return metrics


def main():
    renderer = None
    for line in sys.stdin:
        started = time.monotonic()
        try:
            request = json.loads(line)
            # Model libraries can print diagnostics; stdout is only our protocol.
            with redirect_stdout(sys.stderr):
                cold = renderer is None
                if cold: renderer = Renderer()
                metrics = renderer.render(request['text'], request['reference'], request['output'])
            metrics.update(cold=cold, worker_seconds=time.monotonic()-started)
            response = {'ok':True, 'metrics':metrics}
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Exit on failure so partially moved GPU state cannot outlive the slot.
            print(json.dumps({'ok':False,'error':type(exc).__name__}), flush=True)
            return
        print(json.dumps(response), flush=True)


if __name__ == '__main__':main()
