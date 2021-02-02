from models import model
import torch, utils
import numpy as np
from torch.distributions.normal import Normal

unsqueeze = lambda x : torch.unsqueeze(torch.unsqueeze(x, 0), -1)

class expSmoothing_stimside(model.Model):
    '''
        Model where the prior is based on an exponential estimation of the previous stimulus side
    '''

    def __init__(self, path_to_results, session_uuids, mouse_name, actions, stimuli, stim_side, repetition_bias=False):
        name = 'expSmoothingStimSides' + '_with_repBias' * repetition_bias
        nb_params, lb_params, ub_params = 5, np.array([0, 0, 0, 0, 0]), np.array([1, 1, 1, .5, .5])
        std_RW = np.array([0.04, 0.02, 0.02, 0.01, 0.01])
        initial_point = np.array([0.5, 0.5, 0.5, 0.1, 0.1])
        self.repetition_bias = repetition_bias
        if repetition_bias:
            nb_params += 1
            lb_params, ub_params, initial_point = np.append(lb_params, 0), np.append(ub_params, .5), np.append(initial_point, 0)
            std_RW = np.array([0.02, 0.02, 0.02, 0.01, 0.01, 0.01])        
        super().__init__(name, path_to_results, session_uuids, mouse_name, actions, stimuli, stim_side, nb_params, lb_params, ub_params, std_RW, initial_point)

    def compute_lkd(self, arr_params, act, stim, side, return_details):
        nb_chains = len(arr_params)
        if not self.repetition_bias:
            alpha, zeta_pos, zeta_neg, lapse_pos, lapse_neg = torch.tensor(arr_params).T
        else:
            alpha, zeta_pos, zeta_neg, lapse_pos, lapse_neg, rep_bias = torch.tensor(arr_params).T
        loglikelihood = np.zeros(nb_chains)
        act, stim, side = torch.tensor(act), torch.tensor(stim), torch.tensor(side)
        nb_sessions = len(act)
        
        values = torch.zeros([nb_sessions, nb_chains, self.nb_trials, 2], dtype=torch.float64) + 0.5

        alpha = unsqueeze(alpha)
        zetas = unsqueeze(zeta_pos) * (torch.unsqueeze(side,1) > 0) + unsqueeze(zeta_neg) * (torch.unsqueeze(side,1) <= 0)
        lapses = unsqueeze(lapse_pos) * (torch.unsqueeze(side,1) > 0) + unsqueeze(lapse_neg) * (torch.unsqueeze(side,1) <= 0)

        for t in range(self.nb_trials):
            s = side[:, t]
            if t > 0:
                s_prev = torch.stack([side[:, t - 1]==-1, side[:, t - 1]==1]) * 1
                values[act[:,t-1]!=0, :, t] = (1 - alpha) * values[act[:,t-1]!=0, :, t-1] + alpha * torch.unsqueeze(s_prev.T[act[:,t-1]!=0], 1)
                values[act[:,t-1]==0, :, t] = values[act[:,t-1]==0, :, t-1]

        assert(torch.max(torch.abs(torch.sum(values, axis=-1) - 1)) < 1e-6)

        Rho = torch.minimum(torch.maximum(Normal(loc=torch.unsqueeze(stim, 1), scale=zetas).cdf(0), torch.tensor(1e-7)), torch.tensor(1 - 1e-7)) # pRight likelihood
        pRight, pLeft = values[:, :, :, 0] * Rho, values[:, :, :, 1] * (1 - Rho)
        pActions = torch.stack((pRight/(pRight + pLeft), pLeft/(pRight + pLeft)))

        unsqueezed_lapses = torch.unsqueeze(lapses, 0)

        if self.repetition_bias:
            unsqueezed_rep_bias = torch.unsqueeze(torch.unsqueeze(torch.unsqueeze(rep_bias, 0), 0), -1)            
            pActions[:,:,:,0] = pActions[:,:,:,0] * (1 - unsqueezed_lapses[:,:,:,0]) + unsqueezed_lapses[:,:,:,0] / 2.
            pActions[:,:,:,1:] = pActions[:,:,:,1:] * (1 - unsqueezed_lapses[:,:,:,1:] - unsqueezed_rep_bias) + unsqueezed_lapses[:,:,:,1:] / 2. + unsqueezed_rep_bias * torch.unsqueeze(torch.stack(((act[:,:-1]==-1) * 1, (act[:,:-1]==1) * 1)), 2)
        else:
            pActions = pActions * (1 - torch.unsqueeze(lapses, 0)) + torch.unsqueeze(lapses, 0) / 2.

        p_ch     = pActions[0] * (torch.unsqueeze(act, 1) == -1) + pActions[1] * (torch.unsqueeze(act, 1) == 1) + 1 * (torch.unsqueeze(act, 1) == 0) # discard trials where agent did not answer
        p_ch     = torch.minimum(torch.maximum(p_ch, torch.tensor(1e-8)), torch.tensor(1 - 1e-8))
        logp_ch  = torch.log(p_ch)
        if return_details:
            return np.array(torch.sum(logp_ch, axis=(0, -1))), values
        return np.array(torch.sum(logp_ch, axis=(0, -1)))

        