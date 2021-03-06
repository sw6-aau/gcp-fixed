import argparse
import math
import time

import torch
import torch.nn as nn
import torchvision
import torchvision.transforms as transforms
from models import AENet
from models import LSTNet
from models import AECLSTNet
import numpy as np
import importlib
import numpy
import sys

import pandas as pd

from utils_predict import *
import Optim


# Passes the data-set as input to the model in small batches
# After the data-set has been fully parsed, the output is compared to the original data-set.
def evaluate(data, X, Y, model, evaluateL2, evaluateL1, batch_size):
    model.eval()
    total_loss = 0
    total_loss_l1 = 0
    n_samples = 0
    predict = None
    test = None
    
    # Iterates through all the batches as inputs.
    for X, Y in data.get_batches(X, Y, batch_size, False):
        output = model(X.float());
        if predict is None:
            predict = output
            test = Y
        else:
            predict = torch.cat((predict,output))
            test = torch.cat((test, Y))
        # Extra modifications and loss calculation
        scale = data.scale.expand(output.size(0), data.m)
        total_loss += evaluateL2(output * scale, Y * scale).data
        total_loss_l1 += evaluateL1(output * scale, Y * scale).data
        n_samples += (output.size(0) * data.m);
    rse = math.sqrt(total_loss / n_samples)/data.rse
    rae = (total_loss_l1/n_samples)/data.rae
    # Calculates correlation
    predict = predict.data.cpu().numpy()
    Ytest = test.data.cpu().numpy()
    sigma_p = predict.std(axis = 0)
    sigma_g = Ytest.std(axis = 0)
    mean_p = predict.mean(axis = 0)
    mean_g = Ytest.mean(axis = 0)
    index = sigma_g!=0
    correlation = ((predict - mean_p) * (Ytest - mean_g)).mean(axis = 0)/(sigma_p * sigma_g)
    correlation = (correlation[index]).mean()
    return rse, rae, correlation, predict       # Has added so it also returns the concatenated predicted matrix
    
parser = argparse.ArgumentParser(description='PyTorch Time series forecasting')
parser.add_argument('--data', type=str, required=True,
                    help='location of the data file')
parser.add_argument('--model', type=str, default='LSTNet',
                    help='')
parser.add_argument('--hidCNN', type=int, default=100,
                    help='number of CNN hidden units')
parser.add_argument('--hidRNN', type=int, default=100,
                    help='number of RNN hidden units')
parser.add_argument('--window', type=int, default=24 * 7,
                    help='window size')
parser.add_argument('--CNN_kernel', type=int, default=6,
                    help='the kernel size of the CNN layers')
parser.add_argument('--highway_window', type=int, default=24,
                    help='The window size of the highway component')
parser.add_argument('--clip', type=float, default=10.,
                    help='gradient clipping')
parser.add_argument('--epochs', type=int, default=10,
                    help='upper epoch limit')
parser.add_argument('--batch_size', type=int, default=128, metavar='N',
                    help='batch size')
parser.add_argument('--dropout', type=float, default=0.2,
                    help='dropout applied to layers (0 = no dropout)')
parser.add_argument('--seed', type=int, default=54321,
                    help='random seed')
parser.add_argument('--gpu', type=int, default=None)
parser.add_argument('--log_interval', type=int, default=2000, metavar='N',
                    help='report interval')
parser.add_argument('--save', type=str,  default='model/model.pt',
                    help='path to save the final model')
parser.add_argument('--cuda', type=str, default=True)
parser.add_argument('--optim', type=str, default='adam')
parser.add_argument('--lr', type=float, default=0.001)
parser.add_argument('--horizon', type=int, default=12)
parser.add_argument('--skip', type=float, default=24)
parser.add_argument('--hidSkip', type=int, default=5)
parser.add_argument('--L1Loss', type=bool, default=True)
parser.add_argument('--normalize', type=int, default=2)
parser.add_argument('--output_fun', type=str, default='sigmoid')
args = parser.parse_args()

args.cuda = args.gpu is not None
if args.cuda:
    torch.cuda.set_device(args.gpu)
# Set the random seed manually for reproducibility.
torch.manual_seed(args.seed)
if torch.cuda.is_available():
    if not args.cuda:
        print("WARNING: You have a CUDA device, so you should probably run with --cuda")
    else:
        torch.cuda.manual_seed(args.seed)

Data = Data_utility(args.data, 0.0, 0.0, args.cuda, args.horizon, args.window, args.normalize)
print(Data.rse)

model = eval("LSTNet").Model(args, Data)

if args.cuda:
    model.cuda()
    
nParams = sum([p.nelement() for p in model.parameters()])
print('* number of parameters: %d' % nParams)

if args.L1Loss:
    criterion = nn.L1Loss(size_average=False)
else:
    criterion = nn.MSELoss(size_average=False)
evaluateL2 = nn.MSELoss(size_average=False)
evaluateL1 = nn.L1Loss(size_average=False)
if args.cuda:
    criterion = criterion.cuda()
    evaluateL1 = evaluateL1.cuda()
    evaluateL2 = evaluateL2.cuda()
    
optim = Optim.Optim(
    model.parameters(), args.optim, args.lr, args.clip,
)

#test_noisy = add_noise(Data.test[0])

# Load the best saved model.
# Have changed the train- and validation to 0, so it testes on all the data
with open(args.save, 'rb+') as f:
    checkpoint = torch.load(f)
model.load_state_dict(checkpoint['model_state_dict'])	
optim.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

test_acc, test_rae, test_corr, prediction_tensor  = evaluate(Data, Data.test[0], Data.test[1], model, evaluateL2, evaluateL1, args.batch_size)
print("test rse {:5.4f} | test rae {:5.4f} | test corr {:5.4f}".format(test_acc, test_rae, test_corr))

clean_input = Data.test[1].data.cpu().numpy()
inputpd = pd.DataFrame(clean_input)
inputpd.to_csv("input.csv", index=False)

df = pd.DataFrame(prediction_tensor)
df.to_csv("output.csv", index=False)
