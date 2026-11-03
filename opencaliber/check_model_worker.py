"""Short-lived optional Transformers worker. No downloaded Python is executed."""
import json
from pathlib import Path
import sys

def main():
    operation,folder,model=sys.argv[1:];path=Path(folder)
    if operation=='download':
        from huggingface_hub import HfApi,snapshot_download
        info=HfApi().model_info(model,files_metadata=True)
        wanted=[s for s in info.siblings if s.rfilename.endswith(('.safetensors','.json','.txt','.model','.jinja'))]
        size=sum(s.size or 0 for s in wanted)
        if size>8*1024**3:raise ValueError('Model exceeds the 8 GiB managed download limit')
        snapshot_download(model,revision=info.sha,local_dir=path,allow_patterns=['*.safetensors','*.json','*.txt','*.model','*.jinja'])
        if not list(path.glob('*.safetensors')):raise ValueError('No Safetensors weights')
        (path/'opencaliber-model.json').write_text(json.dumps({'model':model,'revision':info.sha,'bytes':size}),encoding='utf-8')
        print('Downloaded')
    else:
        import torch
        from transformers import AutoTokenizer,AutoModelForCausalLM
        prompt=sys.stdin.read(50000)
        tokenizer=AutoTokenizer.from_pretrained(path,local_files_only=True,trust_remote_code=False)
        model=AutoModelForCausalLM.from_pretrained(path,local_files_only=True,trust_remote_code=False,use_safetensors=True)
        model.eval()
        if torch.cuda.is_available():model=model.to('cuda')
        messages=[{'role':'user','content':prompt}]
        text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True) if tokenizer.chat_template else prompt
        inputs=tokenizer(text,return_tensors='pt',truncation=True,max_length=8192).to(model.device)
        with torch.inference_mode():result=model.generate(**inputs,max_new_tokens=2500,do_sample=False)
        print(tokenizer.decode(result[0][inputs['input_ids'].shape[-1]:],skip_special_tokens=True))

if __name__=='__main__':main()
