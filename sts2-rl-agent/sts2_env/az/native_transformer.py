"""Generic property/entity Transformer. Model IDs are data, never a registration list."""
import hashlib
import math
from functools import lru_cache
import torch
from torch import nn
from .native_generic import CONTENT, SCHEMA, SCHEMA_HASH, leaves, validate_packed
from .rewards import V7

ARCHITECTURE = 'native-property-transformer-v1'
TOKEN_HASH_CACHE_ENABLED = True


@lru_cache(maxsize=65536)
def token_ids(token, buckets):
    """Cache only immutable token hashes; numeric values and validation stay live."""
    digest = hashlib.sha256(token.encode()).digest()
    return (int.from_bytes(digest[:4], 'little') % buckets,
            int.from_bytes(digest[4:8], 'little') % buckets)


def batch_native(observations,device='cpu',*,value_only=False):
    for p in observations: validate_packed(p,value_only=value_only)
    hash_token = token_ids if TOKEN_HASH_CACHE_ENABLED else token_ids.__wrapped__
    b=len(observations); n=max(len(p['entities']) for p in observations); a=max(len(p['actions']) for p in observations)
    ids=[]; values=[]; owners=[]; objects=[]
    entity_mask=torch.zeros(b,n,dtype=torch.bool,device=device)
    legal_mask=torch.zeros(b,a,dtype=torch.bool,device=device)
    for bi,p in enumerate(observations):
        entity_mask[bi,:len(p['entities'])]=True; legal_mask[bi,:len(p['actions'])]=True
        group=p['entities']+[x['features'] for x in p['actions']]
        for i,obj in enumerate(group):
            owner=bi*(n+a)+(i if i<len(p['entities']) else n+i-len(p['entities']))
            for path,value in leaves(obj):
                numeric=type(value) in (float,int)
                token=path+(':number' if numeric else ':'+repr(value))
                ids.append(hash_token(token, SCHEMA['buckets']))
                values.append([math.copysign(math.log1p(abs(value)),value),1.] if numeric else [0.,0.])
                owners.append(owner)
    return dict(ids=torch.tensor(ids,dtype=torch.long,device=device),numbers=torch.tensor(values,dtype=torch.float32,device=device),
        owners=torch.tensor(owners,dtype=torch.long,device=device),shape=(b,n,a),entity_mask=entity_mask,legal_mask=legal_mask,
        action_keys=tuple(tuple(x['key'] for x in p['actions']) for p in observations))


class NativeTransformer(nn.Module):
    def __init__(self,config):
        super().__init__(); self.config=config
        self.content_version=CONTENT; self.reward_version=V7; self.information_mode='observable'
        width=config.d_model
        self.fields=nn.Embedding(SCHEMA['buckets'],width)
        self.fields2=nn.Embedding(SCHEMA['buckets'],width)
        self.numbers=nn.Linear(2,width)
        self.feature=nn.Sequential(nn.LayerNorm(width),nn.Linear(width,width),nn.GELU())
        layer=nn.TransformerEncoderLayer(width,config.heads,width*4,dropout=0.,batch_first=True,norm_first=True)
        self.encoder=nn.TransformerEncoder(layer,config.layers,enable_nested_tensor=False)
        self.attention=nn.MultiheadAttention(width,config.heads,batch_first=True)
        self.policy=nn.Sequential(nn.Linear(width*2,width),nn.GELU(),nn.Linear(width,1))
        self.value=nn.Sequential(nn.Linear(width,width),nn.GELU(),nn.Linear(width,1),nn.Tanh())

    def _state(self,batch):
        b,n,a=batch['shape']; owners=batch['owners']
        features=self.feature(self.fields(batch['ids'][:,0])+self.fields2(batch['ids'][:,1])+self.numbers(batch['numbers']))
        summed=features.new_zeros(b*(n+a),features.shape[-1]).index_add(0,owners,features)
        counts=features.new_zeros(b*(n+a),1).index_add(0,owners,features.new_ones(len(owners),1))
        objects=(summed/counts.clamp_min(1)).reshape(b,n+a,-1)
        state=self.encoder(objects[:,:n],src_key_padding_mask=~batch['entity_mask'])
        pooled=(state*batch['entity_mask'][...,None]).sum(1)/batch['entity_mask'].sum(1,keepdim=True)
        return state,objects[:,n:],self.value(pooled).squeeze(-1)

    def forward(self,batch):
        state,action,value=self._state(batch)
        context,_=self.attention(action,state,state,key_padding_mask=~batch['entity_mask'],need_weights=False)
        logits=self.policy(torch.cat([action,context],dim=-1)).squeeze(-1)
        return logits,value

    @torch.inference_mode()
    def predict_value(self,observation):
        batch=batch_native([observation],next(self.parameters()).device,value_only=True)
        return float(self._state(batch)[2][0])

    @torch.inference_mode()
    def predict(self,observation):
        batch=batch_native([observation],next(self.parameters()).device)
        logits,value=self(batch)
        probabilities=logits[0].softmax(-1).tolist()
        return dict(zip(batch['action_keys'][0],probabilities)),float(value[0])
