#!/usr/bin/env python3
"""Audit a pretrained GPT-Neo config against the current no-DDR RAM budget.

This is a necessary-condition memory audit, not model inference or a quantizer.
Embedding alone is a lower bound; firmware, other weights and activations need
additional storage. KV values assume a full, uncompressed cache on all layers.
"""
import argparse,hashlib,json
from pathlib import Path

def audit(config,ram_bytes=65536,context=128):
 v,d,l=config['vocab_size'],config['hidden_size'],config['num_layers']
 embedding=v*d
 return {'model':'roneneldan/TinyStories-1M','architecture':config['architectures'][0],
         'board_ram_bytes':ram_bytes,'available_ddr_bytes':0,
         'embedding_parameters':embedding,'embedding_int8_lower_bound_bytes':embedding,
         'embedding_int4_lower_bound_bytes':(embedding+1)//2,
         'embedding_int8_ram_multiple':embedding/ram_bytes,
         'full_float32_logits_bytes':v*4,'context_tokens':context,
         'kv_cache_float32_bytes':2*l*context*d*4,
         'embedding_int8_fits':embedding<=ram_bytes,
         'full_float32_logits_fit':v*4<=ram_bytes,
         'kv_cache_float32_fits':2*l*context*d*4<=ram_bytes,
         'admitted':embedding<=ram_bytes,
         'reasons':['Even int8 embedding weights alone exceed the entire physical RAM.','Quantization scales, all other weights, firmware, activations and stack are additional.','Materialized full-vocabulary float32 logits and an uncompressed KV cache exceed RAM too.'],
         'possible_future_routes':['Board DDR with verified memory runtime','On-board flash/DDR weight streaming and tiled vocabulary projection','Smaller pretrained model or explicit vocabulary/model changes'],
         'not_claimed':['Full model compilation','Pretrained text generation on KC705','Inference FPS or tokens/sec','Actual int8 or int4 quantized model accuracy']}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--context',type=int,default=128);a=p.parse_args()
 if a.context<1:p.error('--context must be positive')
 report=audit(json.loads(a.config.read_text()),context=a.context);report['config_sha256']=hashlib.sha256(a.config.read_bytes()).hexdigest();a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
