import sys
import os

current_file_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_file_path + '/../../')

import socket
import collections
import numpy as np
import argparse
import joblib
import time
from types import SimpleNamespace
import torch
from torch.nn import functional as F

from garage import wrap_experiment
from garage.envs import GarageEnv
from garage.experiment.deterministic import set_seed
from garage.experiment import SnapshotConfig

from envs import PredatorPreyWrapper
from dicg.torch.baselines import GaussianMLPBaseline
from dicg.torch.algos import CentralizedMAPPO
from dicg.torch.policies import DecCategoricalMLPPolicy
from dicg.experiment.local_runner_wrapper import LocalRunnerWrapper
from dicg.sampler import CentralizedMAOnPolicyVectorizedSampler

def run(args):
    
    if args.exp_name is None:
        exp_layout = collections.OrderedDict([
            ('dec_ppo{}', ''),
            ('entcoeff={}', args.ent),
            ('grid={}', args.grid_size),
            ('nagents={}', args.n_agents),
            ('npreys={}', args.n_preys),
            ('penalty={:.2f}', args.penalty),
            ('stepcost={:.2f}', args.step_cost),
            ('avis={}', bool(args.agent_visible)),
            ('steps={}', args.max_env_steps),
            ('nenvs={}', args.n_envs),
            ('bs={:0.0e}', args.bs),
            ('splits={}', args.opt_n_minibatches),
            ('miniepoch={}', args.opt_mini_epochs),
            ('seed={}', args.seed)
        ])

        exp_name = '_'.join([key.format(val) for key, val in exp_layout.items()])

    else:
        exp_name = args.exp_name

    prefix = 'predatorprey'
    id_suffix = ('_' + str(args.run_id)) if args.run_id != 0 else ''
    exp_dir = './data/' + args.loc +'/' + exp_name + id_suffix

    # Enforce
    args.center_adv = False if args.entropy_method == 'max' else args.center_adv

    if args.mode == 'train':
        # making sequential log dir if name already exists
        @wrap_experiment(name=exp_name, prefix=prefix, log_dir=exp_dir, snapshot_mode='last', snapshot_gap=1)
        
        def train_predatorprey(ctxt=None, args_dict=vars(args)):

            args = SimpleNamespace(**args_dict)
            set_seed(args.seed)

            env = PredatorPreyWrapper(
                centralized=True, # centralized training
                grid_shape=(args.grid_size, args.grid_size),
                n_agents=args.n_agents,
                n_preys=args.n_preys,
                max_steps=args.max_env_steps,
                step_cost=args.step_cost,
                prey_capture_reward=args.capture_reward,
                penalty=args.penalty,
                other_agent_visible=args.agent_visible
            )
            env = GarageEnv(env)

            runner = LocalRunnerWrapper(
                ctxt,
                eval=args.eval_during_training,
                n_eval_episodes=args.n_eval_episodes,
                eval_greedy=args.eval_greedy,
                eval_epoch_freq=args.eval_epoch_freq,
                save_env=env.pickleable
            )

            hidden_nonlinearity = F.relu if args.hidden_nonlinearity == 'relu' \
                                    else torch.tanh

            policy = DecCategoricalMLPPolicy(
                env.spec,
                env.n_agents,
                hidden_nonlinearity=hidden_nonlinearity,
                hidden_sizes=args.hidden_sizes,
                name='dec_categorical_mlp_policy')

            baseline = GaussianMLPBaseline(env_spec=env.spec, hidden_sizes=(64, 64, 64))
            
            algo = CentralizedMAPPO(
                env_spec=env.spec,
                policy=policy,
                baseline=baseline,
                max_path_length=args.max_env_steps, # Notice
                discount=args.discount,
                center_adv=bool(args.center_adv),
                positive_adv=bool(args.positive_adv),
                gae_lambda=args.gae_lambda,
                policy_ent_coeff=args.ent,
                entropy_method=args.entropy_method,
                stop_entropy_gradient = True \
                   if args.entropy_method == 'max' else False,
                optimization_n_minibatches=args.opt_n_minibatches,
                optimization_mini_epochs=args.opt_mini_epochs,
            )

            # algo (garage.np.algos.RLAlgorithm): An algorithm instance.
            # env (garage.envs.GarageEnv): An environement instance.
            # sampler_cls (garage.sampler.Sampler): A sampler class.
            # sampler_args (dict): Arguments to be passed to sampler constructor.
            
            runner.setup(algo, env, sampler_cls=CentralizedMAOnPolicyVectorizedSampler, sampler_args={'n_envs': args.n_envs})
            # runner.train(n_epochs=args.n_epochs, batch_size=args.bs)

        train_predatorprey(args_dict=vars(args))

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()

    # Meta
    parser.add_argument('--mode', '-m', type=str, default='train')
    parser.add_argument('--loc', type=str, default='local')
    parser.add_argument('--exp_name', type=str, default=None)

    # Train
    parser.add_argument('--seed', '-s', type=int, default=1)
    parser.add_argument('--n_epochs', type=int, default=1000)
    parser.add_argument('--bs', type=int, default=40000)
    parser.add_argument('--n_envs', type=int, default=1)

    # Eval
    parser.add_argument('--run_id', type=int, default=0)
    parser.add_argument('--n_eval_episodes', type=int, default=100)
    parser.add_argument('--render', type=int, default=1)
    parser.add_argument('--eval_during_training', type=int, default=1)
    parser.add_argument('--eval_greedy', type=int, default=1)
    parser.add_argument('--eval_epoch_freq', type=int, default=1)

    # Env
    parser.add_argument('--max_env_steps', type=int, default=200)
    parser.add_argument('--grid_size', type=int, default=10)
    parser.add_argument('--n_agents', '-n', type=int, default=8)
    parser.add_argument('--n_preys', type=int, default=8)
    parser.add_argument('--step_cost', type=float, default=-0.1)
    parser.add_argument('--penalty', type=float, default=0)
    parser.add_argument('--capture_reward', type=float, default=10)
    parser.add_argument('--agent_visible', type=int, default=1)


    # Algo
    parser.add_argument('--hidden_nonlinearity', type=str, default='tanh')
    parser.add_argument('--discount', type=float, default=0.99)
    parser.add_argument('--center_adv', type=int, default=1)
    parser.add_argument('--positive_adv', type=int, default=0)
    parser.add_argument('--gae_lambda', type=float, default=0.97)
    parser.add_argument('--ent', type=float, default=0.1)
    parser.add_argument('--entropy_method', type=str, default='regularized')
    parser.add_argument('--opt_n_minibatches', type=int, default=3, help='The number of splits of a batch of trajectories for optimization.')
    parser.add_argument('--opt_mini_epochs', type=int, default=10, help='The number of epochs the optimizer runs for each batch of trajectories.')
    
    # Policy
    parser.add_argument('--hidden_sizes', type=list, default=[128, 64, 32])

    args = parser.parse_args()

    run(args)



