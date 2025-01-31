import torch
import encoder
import math
import random
import sys
import argparse

ap = argparse.ArgumentParser()
ap.add_argument('--length', type=int, default=100)
ap.add_argument('--steps', type=int, default=100)
ap.add_argument('--big', dest='big', type=float, default=1.)
ap.add_argument('--eps', dest='eps', type=float, default=1e-5)
ap.add_argument('--bad', dest='bad', action='store_true', default=False)
args = ap.parse_args()

alphabet = ["0", "1", "$"]
alphabet_index = {a:i for i,a in enumerate(alphabet)}
max_pos = 10000

log_sigmoid = torch.nn.LogSigmoid()

class PositionEncoding(torch.nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, n):
        zero = torch.zeros(n)
        pos = torch.arange(0, n).to(torch.float)
        pe = torch.stack([zero]*3 +
                         [pos == 1] +
                         [zero]*2,
                         dim=1)
        return pe

class FirstLayer(torch.nn.TransformerEncoderLayer):
    def __init__(self):
        super().__init__(12, 1, 1, dropout=0.)
        self.self_attn.in_proj_weight = torch.nn.Parameter(torch.zeros(36,12))
        self.self_attn.in_proj_bias = torch.nn.Parameter(torch.zeros(36))

        self.self_attn.out_proj.weight = torch.nn.Parameter(torch.zeros(12,12))
        self.self_attn.out_proj.bias = torch.nn.Parameter(torch.zeros(12))

        self.linear1.weight = torch.nn.Parameter(torch.tensor([
            [-1,0,-1,1,0,0, 0,0,0,0,0,0],
        ], dtype=torch.float))
        self.linear1.bias = torch.nn.Parameter(torch.tensor([0.]))
        self.linear2.weight = torch.nn.Parameter(torch.tensor(
            [[0]]*4 +
            [[1],
             [0]] +
            [[0]]*4 +
            [[-1],
             [0]],
            dtype=torch.float))
        self.linear2.bias = torch.nn.Parameter(torch.zeros(12))

        self.norm1.eps = self.norm2.eps = args.eps
    
    def forward(self, src, src_mask=None, src_key_padding_mask=None):
        src2 = self.self_attn(src, src, src, attn_mask=src_mask,
                              key_padding_mask=src_key_padding_mask)[0]
        src = src + self.dropout1(src2)
        src = self.norm1(src)
        src2 = self.linear2(self.dropout(self.activation(self.linear1(src))))
        src = src + self.dropout2(src2)
        src = self.norm2(src)
        return src

class SecondLayer(torch.nn.TransformerEncoderLayer):
    def __init__(self):
        super().__init__(12, 1, 12, dropout=0.)
        self.self_attn.in_proj_weight = torch.nn.Parameter(torch.tensor(
            # W^Q
            [[0,0,args.big,0,0,0, 0,0,0,0,0,0]] +
            [[0]*12]*11 +
            # W^K
            [[0,0,0,1,0,0, 0,0,0,0,0,0]] +
            [[0]*12]*11 +
            # W^V
            [[0]*12]*5 +
            [[0,0,0,-0.5,1,0, 0,0,0,0,0,0]] +
            [[0]*12]*6,
            dtype=torch.float))

        self.self_attn.in_proj_bias = torch.nn.Parameter(torch.zeros(36))

        self.self_attn.out_proj.weight = torch.nn.Parameter(torch.tensor(
            # W^O
            [[0]*12]*5 +
            [[0,0,0,0,0,1, 0,0,0,0,0,0]] +
            [[0]*12]*5 +
            [[0,0,0,0,0,-1, 0,0,0,0,0,0]],
            dtype=torch.float))
        self.self_attn.out_proj.bias = torch.nn.Parameter(torch.zeros(12))

        self.linear1.weight = torch.nn.Parameter(torch.eye(12))
        self.linear1.bias = torch.nn.Parameter(torch.zeros(12))
        w = torch.cat((torch.cat((-torch.eye(6), torch.eye(6)), dim=1),
                       torch.cat((torch.eye(6), -torch.eye(6)), dim=1)))
        # Preserve dim 5
        w[5,5] = w[5,11] = w[11,5] = w[11,11] = 0
        self.linear2.weight = torch.nn.Parameter(w)
        self.linear2.bias = torch.nn.Parameter(torch.zeros(12))

        self.norm1.eps = self.norm2.eps = args.eps

    forward = FirstLayer.forward

class MyTransformerEncoder(torch.nn.TransformerEncoder):
    def __init__(self):
        torch.nn.Module.__init__(self)

        self.layers = torch.nn.ModuleList([
            FirstLayer(),
            SecondLayer(),
        ])
        self.num_layers = len(self.layers)
        self.norm = None

class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        
        self.word_embedding = torch.eye(3, 6)
        self.word_embedding.requires_grad = True
        self.pos_encoding = PositionEncoding()
        self.transformer_encoder = MyTransformerEncoder()
        self.output_layer = torch.nn.Linear(12, 1)
        self.output_layer.weight = torch.nn.Parameter(torch.tensor(
            [[0,0,0,0,0,1,0,0,0,0,0,0]], dtype=torch.float))
        self.output_layer.bias = torch.nn.Parameter(torch.tensor([0.]))

    def forward(self, w):
        x = self.word_embedding[w] + self.pos_encoding(len(w))
        x = torch.cat([x, -x], dim=-1)
        y = self.transformer_encoder(x.unsqueeze(1)).squeeze(1)
        z = self.output_layer(y[0])
        return z

model = Model()

loss = 0
total = 0
correct = 0
for step in range(args.steps):
    n = args.length
    w = torch.tensor([alphabet_index['$']] + [alphabet_index[str(random.randrange(2))] for i in range(n)])
    label = w[1] == alphabet_index['1']
    output = model(w)
    output.backward()
    for z, p in enumerate(model.parameters()):
      print(p.size(), p.grad.abs().max(), z)
    quit()
    print(output)
    print("Embedding", model.word_embedding.grad.abs().max())
    print("something from a layer", model.transformer_encoder.layers[0].linear1.weight.grad.abs().max())
    print("Output", model.output_layer.weight.grad.abs().max())
    print("Output", model.output_layer.bias.grad.abs().max())
    quit()
    if not label: output = -output
    if output > 0:
        correct += 1
    total += 1
    loss -= log_sigmoid(output).item()
print(f'length={n} ce={loss/total/math.log(2)} acc={correct/total}')
