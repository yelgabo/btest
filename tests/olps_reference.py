"""Reference implementations: the authors' original functions, copied verbatim from
github.com/nglahani/Online-Quantitative-Trading-Strategies at commit 7c2e88d
(Scripts/Strategies/*.py) so tests can compare btest.olps against them. Only changes: imports
flattened into one module, joblib.Parallel replaced by a plain loop, unused code removed.

Original license:

MIT License

Copyright (c) 2024 Nikolos Lahanis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
# ruff: noqa
import numpy as np
from scipy.optimize import minimize



def project_to_simplex(v):
    """ Project the vector v onto the probability simplex (sum to 1 and all entries >= 0). """
    n = len(v)
    # Sort v in descending order
    u = np.sort(v)[::-1]
    cssv = np.cumsum(u) - 1
    rho = np.nonzero(u > cssv / np.arange(1, n+1))[0][-1]
    theta = cssv[rho] / (rho + 1.0)
    return np.maximum(v - theta, 0)

def calculate_l1_median(data, max_iter=100, tol=1e-5):
    mu = np.mean(data, axis=0)  # Initial guess
    for _ in range(max_iter):
        distances = np.linalg.norm(data - mu, axis=1)
        distances[distances < 1e-10] = 1e-10  # Avoid divide-by-zero
        weights = 1.0 / distances[:, np.newaxis]
        mu_new = np.sum(weights * data, axis=0) / np.sum(weights, axis=0)
        if np.linalg.norm(mu_new - mu) < tol:
            break
        mu = mu_new
    return mu


##############################################################################
# FOLLOW-THE-WINNER ALGORITHMS (Optimized)
##############################################################################



# Strategy 4: Universal Portfolios (Approximation)
def universal_portfolios(b, price_relative_vectors, num_portfolios=3, tau=.3):
    """
    Cover's Universal Portfolios, approximated by sampling 'num_portfolios' random points
    on the simplex. We track the wealth of each sampled portfolio over time and then 
    blend them by their (normalized) wealth to form a final "universal" portfolio each step.
    
    Hyperparameters:
    - num_portfolios: number of random portfolios to sample.
    - tau: wealth weighting temperature. When tau=1, weights are the raw wealth.
           When tau > 1, higher performing portfolios get more emphasis.
           When tau < 1, the influence of wealth differences is softened.
           
    Parameters:
    - price_relative_vectors: A 2D NumPy array of shape (T, N) where T is the number of time periods
      and N is the number of assets.
    
    Returns:
    - b_n: A 2D NumPy array of shape (T, N) representing the blended portfolio at each period.
    """
    T, N = price_relative_vectors.shape
    
    # Sample many random portfolios on the simplex
    portfolios = np.random.dirichlet(np.ones(N), size=num_portfolios)  # shape (num_portfolios, N)
    
    # Each portfolio starts with wealth = 1.0
    wealth = np.ones(num_portfolios)
    b_n = np.zeros((T, N))
    
    for t in range(T):
        # Compute weighted average of sampled portfolios using wealth**tau as weights
        weights = wealth ** tau
        w_t = np.average(portfolios, axis=0, weights=weights)
        w_t /= w_t.sum()  # Ensure the portfolio sums to 1
        b_n[t] = w_t

        # Update wealth based on the observed price relatives x_t
        x_t = price_relative_vectors[t]
        portfolio_returns = portfolios.dot(x_t)
        wealth *= portfolio_returns

    return b_n


# Strategy 5: Exponential Gradient
def exponential_gradient(b, price_relative_vectors, learning_rate=0.05, smoothing=0.0):
    """
    Implements the exponential gradient update in a vectorized manner with a smoothing parameter.
    
    Parameters:
        b: Initial portfolio vector (numpy array).
        price_relative_vectors: 2D numpy array of price relatives (shape: T x N).
        learning_rate: Learning rate (η) for the exponential gradient update.
        smoothing: Smoothing parameter (α) in [0, 1]. 
                   With α = 1, the update is fully applied; with α < 1, the update is a convex
                   combination of the previous portfolio and the computed update.
                   
    Returns:
        b_n: 2D numpy array where each row is the portfolio vector at a given time step.
    """
    # Debug output to verify parameter values
    # print(f"[DEBUG] exponential_gradient called with learning_rate={learning_rate}, smoothing={smoothing}")
    # print(f"[DEBUG] price_relative_vectors shape: {price_relative_vectors.shape}")
    
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b

    for t in range(1, T):
        x_t = price_relative_vectors[t-1]
        portfolio_return = np.dot(b_n[t-1], x_t)
        # Compute update factor using the exponential gradient formulation
        update_factor = learning_rate * (x_t / (portfolio_return + 1e-15) - 1) + 1
        
        # Compute the updated portfolio weights (before smoothing)
        computed_b = b_n[t-1] * update_factor
        computed_b /= np.sum(computed_b)
        
        # Apply smoothing: interpolate between the old portfolio and the computed update
        new_b = (1 - smoothing) * b_n[t-1] + smoothing * computed_b
        new_b /= np.sum(new_b)
        b_n[t] = new_b

    return b_n



# Strategy 6: Follow-The-Leader
def follow_the_leader(b_init, price_relative_vectors, gamma=.8, alpha=1.5):
    """Implementation of Follow-the-Leader with stability improvements"""
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b_init.copy()
    
    for t in range(1, T):
        # Calculate historical returns with stability threshold
        historical_returns = np.maximum(np.cumprod(price_relative_vectors[:t], axis=0), 1e-10)
        
        # Calculate weights with power function and stability constant
        weights = np.power(historical_returns[-1], alpha) + 1e-10
        
        # Normalize with numeric stability
        sum_weights = np.sum(weights)
        if sum_weights > 1e-10:
            b_n[t] = weights / sum_weights
        else:
            b_n[t] = np.ones(N) / N  # Fallback to uniform allocation
            
        # Apply momentum factor
        if gamma != 1.0:
            b_n[t] = gamma * b_n[t] + (1 - gamma) * b_n[t-1]
            # Ensure final normalization
            sum_b = np.sum(b_n[t])
            if sum_b > 1e-10:
                b_n[t] /= sum_b
            else:
                b_n[t] = np.ones(N) / N
    
    return b_n

#Strategy 7: Follow the Regularized Leader
def follow_the_regularized_leader(b, price_relative_vectors, beta=0.13, delta=0.925, ridge_const=.015):
    """
    Implements a simplified ONS-style Follow-The-Regularized Leader with an adjustable ridge regularization constant.
    
    Parameters:
    - b: Initial portfolio vector.
    - price_relative_vectors: 2D numpy array with price relative vectors.
    - beta: Hyperparameter controlling the weight on the gradient sum.
    - delta: Scaling factor for the new portfolio update.
    - ridge_const: Ridge regularization constant added to the update of A_t for numerical stability.
    
    Returns:
    - b_n: Updated portfolio trajectory over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b.copy()
    A_t = np.eye(N)
    grad_sum = np.zeros(N)

    for t in range(1, T):
        # Get the price relative at the previous time step
        x_t = price_relative_vectors[t-1]
        port_return = np.dot(b_n[t-1], x_t)
        
        # Update the matrix A_t with the ridge term for numerical stability
        A_t += np.outer(x_t, x_t) / (port_return + 1e-15)**2 + np.eye(N) * ridge_const

        # Incrementally update the gradient sum
        grad_t = x_t / (port_return + 1e-15)
        grad_sum += grad_t

        p_t = (1 + (1 / beta)) * grad_sum
        new_b = np.linalg.inv(A_t).dot(p_t) * delta
        new_b = project_to_simplex(new_b)
        b_n[t] = new_b

    return b_n

#Strategy 8: Aggregation-Based Simple
def aggregation_based_simple(b, price_relative_vectors, learning_rate=0.4, num_base_portfolios=3):
    """
    Aggregates a set of base portfolios using their cumulative performance.
    This version updates the portfolio performance iteratively to avoid
    recomputing the full product over time at each iteration.
    
    Parameters:
        b : numpy array
            The initial portfolio vector.
        price_relative_vectors : numpy array of shape (T, N)
            Matrix where each row represents a period and each column an asset.
        learning_rate : float, default 0.5
            Hyperparameter controlling the influence of cumulative performance.
        num_base_portfolios : int, optional
            The number of base portfolios to generate. If None, defaults to the number of assets (N).
    
    Returns:
        b_n : numpy array of shape (T, N)
            Matrix containing the aggregated portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    if num_base_portfolios is None:
        num_base_portfolios = N

    b_n = np.zeros((T, N))
    b_n[0] = b

    # Generate the base portfolios (tunable number) using a Dirichlet distribution.
    base_portfolios = np.random.dirichlet(np.ones(N), num_base_portfolios)
    prior_weights = np.ones(num_base_portfolios) / num_base_portfolios

    # Initialize cumulative performance for each base portfolio.
    portfolio_performance = np.ones(num_base_portfolios)
    for t in range(T):
        if t > 0:
            # Update cumulative performance iteratively.
            x_t = price_relative_vectors[t-1]
            portfolio_performance *= base_portfolios.dot(x_t)
        adjusted_weights = prior_weights * (portfolio_performance ** learning_rate)
        adjusted_weights /= np.sum(adjusted_weights)
        b_n[t] = adjusted_weights.dot(base_portfolios)

    return b_n


##############################################################################
# FOLLOW-THE-LOSER ALGORITHMS (Optimized)
##############################################################################




# Strategy 9: Anti-Correlation (Anticor) - Simplified and Vectorized
def anticor(b, price_relative_vectors, window_size=3, alpha=2.5, corr_threshold=0.5):
    """
    Implements a simplified anticorrelation strategy with additional parameters.
    
    Parameters:
        b: Initial portfolio weight vector.
        price_relative_vectors: A T x N numpy array where each row is a price relative vector.
        window_size: The window size to compute log-price relatives for correlation estimation.
        alpha: Transfer scaling factor to control aggressiveness.
        corr_threshold: Only correlations above this threshold are used in computing transfers.
        
    Returns:
        b_n: A T x N array representing the portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b

    for t in range(1, T):
        if t >= 2 * window_size:
            # Compute log-price relatives for two successive windows
            y1 = np.log(price_relative_vectors[t - 2*window_size : t - window_size])
            y2 = np.log(price_relative_vectors[t - window_size : t])
            
            if y1.shape[0] > 0 and y2.shape[0] > 0:
                # Compute means (available if needed)
                mean_y1 = np.mean(y1, axis=0)
                mean_y2 = np.mean(y2, axis=0)
                
                # Compute cross-covariance between the two windows.
                # np.cov returns a 2N x 2N matrix, so we take the upper-right quadrant.
                Mcov = np.cov(y1.T, y2.T)[:N, N:]
                std_y1 = np.std(y1, axis=0)
                std_y2 = np.std(y2, axis=0)
                
                # Avoid division by zero
                std_y1[std_y1 == 0] = 1e-10
                std_y2[std_y2 == 0] = 1e-10
                Mcor = Mcov / np.outer(std_y1, std_y2)
                
                # Apply the correlation threshold: only correlations above the threshold are retained.
                pos_corr = np.where(Mcor > corr_threshold, Mcor, 0)
                
                # Compute transfer amounts:
                # For each asset, sum the incoming and outgoing transfer claims from correlations.
                transfer_amounts = np.sum(pos_corr, axis=0) - np.sum(pos_corr, axis=1)
                # Scale the transfer amounts by alpha.
                transfer_amounts *= alpha
                
                # Update the portfolio by applying the transfer amounts,
                # ensuring non-negativity and then renormalizing to sum to one.
                b_star = b_n[t-1] + transfer_amounts
                b_star = np.maximum(b_star, 0)
                if np.sum(b_star) > 0:
                    b_star /= np.sum(b_star)
                b_n[t] = b_star
            else:
                b_n[t] = b_n[t-1]
        else:
            b_n[t] = b_n[t-1]

    return b_n


# Strategy 10: PAMR (Passive Aggressive Mean Reversion)
def pamr(b, price_relative_vectors, epsilon=0.9, C=10.0):
    """
    Implements the PAMR strategy with an additional aggressiveness cap parameter C.
    Uses previous period’s price relatives to compute an adjustment factor.

    Parameters:
      b : numpy array, initial portfolio weights (shape: [N])
      price_relative_vectors : numpy array (shape: [T, N])
      epsilon : sensitivity threshold (default 0.5)
      C : cap for the update step (default 1.0)

    Returns:
      b_n : numpy array of shape (T, N) representing the portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b

    for t in range(1, T):
        x_t = price_relative_vectors[t-1]
        portfolio_return = np.dot(b_n[t-1], x_t)

        x_t_mean = np.mean(x_t)
        x_t_diff = x_t - x_t_mean
        denom = np.linalg.norm(x_t_diff) ** 2

        if denom > 0:
            tau_t = (portfolio_return - epsilon) / (denom + 1e-15)
            tau_t = max(0, tau_t)         # Ensure non-negative tau
            tau_t = min(C, tau_t)         # Cap the update using C
        else:
            tau_t = 0

        b_t1 = b_n[t-1] - tau_t * x_t_diff
        b_t1 = np.maximum(b_t1, 0)
        if np.sum(b_t1) > 0:
            b_t1 /= np.sum(b_t1)
        b_n[t] = b_t1

    return b_n


#Strategy 11: CWMR (Confidence-Weighted Mean Reversion)
def cwmr(b, price_relative_vectors, epsilon=0.89, theta=0.92, eta=.93):
    """
    Implements a simplified version of CWMR with an additional learning rate factor (eta).
    Maintains a mean vector (mu_t) and covariance matrix (Sigma_t) to update the portfolio.

    Parameters:
        b: Initial portfolio (numpy array)
        price_relative_vectors: numpy array with shape (T, N)
        epsilon: Sensitivity parameter for mean reversion (default 0.5)
        theta: Confidence threshold parameter (default 0.95)
        eta: Learning rate factor to scale the update (default 1.0)

    Returns:
        b_n: numpy array of shape (T, N) with portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b.copy()

    mu_t = b.copy().astype(np.float64)
    Sigma_t = np.eye(N) * 1.0

    for t in range(1, T):
        x_t = price_relative_vectors[t-1]
        x_t_mean = np.dot(mu_t, x_t)

        # Compute denominator for lambda_t calculation
        denominator = x_t @ (Sigma_t @ x_t)
        if denominator > 0:
            # Incorporate the learning rate factor (eta)
            lambda_t = eta * max(0, (x_t_mean - epsilon) / (denominator + 1e-15))
        else:
            lambda_t = 0

        # Update the mean vector
        mu_t -= lambda_t * (Sigma_t @ x_t)
        # Update the covariance matrix with a small ridge for numerical stability
        Sigma_t_inv = np.linalg.inv(Sigma_t + np.eye(N) * 1e-12)
        Sigma_t_inv += 2 * lambda_t * theta * np.outer(x_t, x_t)
        Sigma_t = np.linalg.inv(Sigma_t_inv)
        # Project the updated mean to the simplex (ensure portfolio constraints)
        mu_t = project_to_simplex(mu_t)
        b_n[t] = mu_t

    return b_n


#Strategy 12: OLMAR 
def olmar(b, price_relative_vectors, window_size=2, epsilon=.8, eta=20):
    """
    Implements a simplified OLMAR strategy with a learning rate multiplier.
    Uses a moving average of past price relatives as a prediction.

    Parameters:
        b: Initial portfolio (numpy array)
        price_relative_vectors: numpy array of price relative vectors (shape: [T, N])
        window_size: Window length for computing the moving average (default 10)
        epsilon: Threshold for triggering the update (default 0.5)
        eta: Learning rate multiplier to scale the update step (default 1.0)

    Returns:
        b_n: numpy array of shape (T, N) representing the portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b

    for t in range(1, T):
        if t < window_size:
            ma_t = np.mean(price_relative_vectors[:t], axis=0)
        else:
            ma_t = np.mean(price_relative_vectors[t-window_size : t], axis=0)

        # Basic prediction (x_t_tilde) using the moving average
        x_t_tilde = ma_t
        b_t = b_n[t-1]
        x_t_tilde_mean = np.dot(b_t, x_t_tilde)
        if x_t_tilde_mean < epsilon:
            tau = (epsilon - x_t_tilde_mean) / (np.dot(x_t_tilde, x_t_tilde) + 1e-15)
            b_t1 = b_t + eta * tau * (x_t_tilde - b_t)
            b_t1 = project_to_simplex(b_t1)
        else:
            b_t1 = b_t
        b_n[t] = b_t1

    return b_n

#Strategy 13: Robust Median Reversion
def rmr(b, price_relative_vectors, window_size=8, epsilon=1.1, eta=30):
    """
    Implements a robust median reversion (RMR) strategy with an additional learning rate multiplier.
    Uses an L1-median computed over a sliding window of price relatives to form predictions.

    Parameters:
        b: Initial portfolio (numpy array)
        price_relative_vectors: numpy array of price relative vectors (shape: [T, N])
        window_size: Window length for computing the L1-median (default 10)
        epsilon: Threshold for triggering the update (default 0.8)
        eta: Learning rate multiplier to scale the update step (default 1.0)

    Returns:
        b_n: numpy array of shape (T, N) representing the portfolio weights over time.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b.copy()

    for t in range(1, T):
        if t < window_size:
            window_data = price_relative_vectors[:t]
        else:
            window_data = price_relative_vectors[t-window_size : t]

        # Compute the L1-median of the window data
        mu_t_plus_1 = calculate_l1_median(np.array(window_data, dtype=np.float64))
        # Predict next price relatives by comparing the median with last observed prices
        x_t_tilde = mu_t_plus_1 / (price_relative_vectors[t-1] + 1e-15)

        b_t = b_n[t-1]
        x_t_tilde_mean = np.dot(b_t, x_t_tilde)
        if x_t_tilde_mean < epsilon:
            tau = (epsilon - x_t_tilde_mean) / (np.dot(x_t_tilde, x_t_tilde) + 1e-15)
            # Scale the update with eta
            b_t1 = b_t + eta * tau * (x_t_tilde - b_t)
            b_t1 = project_to_simplex(b_t1)
        else:
            b_t1 = b_t
        b_n[t] = b_t1

    return b_n



##############################################################################
# PATTERN-MATCHING FRAMEWORK
##############################################################################



def histogram_based_selection(price_relative_vectors, w=4, bins=[(0,0.5),(0.5,1),(1,1.5)]):
    n = len(price_relative_vectors)
    if n < w:
        return []
    rolling_means = np.array([np.mean(price_relative_vectors[i-w:i], axis=0) for i in range(w,n+1)])
    latest_mean = np.mean(rolling_means[-1])
    latest_bin = next((idx for idx,(low,high) in enumerate(bins) if low <= latest_mean < high), -1)

    C = []
    for i in range(len(rolling_means)-1):
        hist_mean = np.mean(rolling_means[i])
        hist_bin = next((idx for idx,(low,high) in enumerate(bins) if low <= hist_mean < high), -1)
        if hist_bin == latest_bin:
            C.append(i + w)
    return C

def kernel_based_selection(price_relative_vectors, w=5, threshold=0.1):
    n = len(price_relative_vectors)
    if n < w:
        return []
    C = []
    latest_window = np.mean(price_relative_vectors[-w:], axis=0)

    for i in range(w, n):
        historical_window = np.mean(price_relative_vectors[i-w:i], axis=0)
        distance = np.linalg.norm(latest_window - historical_window)
        if distance <= threshold / np.sqrt(w):
            C.append(i)
    return C

def nearest_neighbor_selection(price_relative_vectors, w=3, num_neighbors=5):
    n = len(price_relative_vectors)
    if n < w:
        return []
    latest_window = np.mean(price_relative_vectors[-w:], axis=0)
    distances = []
    for i in range(w, n):
        historical_window = np.mean(price_relative_vectors[i-w:i], axis=0)
        dist = np.linalg.norm(latest_window - historical_window)
        distances.append((i, dist))
    distances.sort(key=lambda x: x[1])
    C = [idx for idx,_ in distances[:num_neighbors]]
    return C

def correlation_based_selection(price_relative_vectors, w=3, rho=0.6):
    n = len(price_relative_vectors)
    if n < w:
        return []
    C = []
    latest_window = np.mean(price_relative_vectors[-w:], axis=0)
    for i in range(w,n):
        historical_window = np.mean(price_relative_vectors[i-w:i], axis=0)
        corr = np.corrcoef(latest_window, historical_window)[0,1]
        if corr >= rho:
            C.append(i)
    return C

def log_optimal_portfolio(C, price_relative_vectors):
    if not C:
        m = price_relative_vectors.shape[1]
        return np.ones(m)/m
    X_C = price_relative_vectors[C]

    def objective(b):
        return -np.sum(np.log(np.dot(X_C,b)+1e-15))/len(C)

    cons = ({'type':'eq','fun':lambda b: np.sum(b)-1})
    bounds = [(0,1)]*price_relative_vectors.shape[1]
    b_init = np.ones(price_relative_vectors.shape[1])/price_relative_vectors.shape[1]
    result = minimize(objective, b_init, method='SLSQP', bounds=bounds, constraints=cons)
    return result.x

def semi_log_optimal_portfolio(C, price_relative_vectors):
    if not C:
        m = price_relative_vectors.shape[1]
        return np.ones(m)/m
    X_C = price_relative_vectors[C]

    def f_z(z):
        return z - 0.5*(z-1)**2

    def objective(b):
        return -np.sum(f_z(np.dot(X_C,b)))/len(C)

    cons = ({'type':'eq','fun':lambda b: np.sum(b)-1})
    bounds = [(0,1)] * price_relative_vectors.shape[1]
    b_init = np.ones(price_relative_vectors.shape[1])/price_relative_vectors.shape[1]
    result = minimize(objective, b_init, method='SLSQP', bounds=bounds, constraints=cons)
    return result.x

def markowitz_portfolio(C, price_relative_vectors, lambda_= 0.7):
    if not C:
        m = price_relative_vectors.shape[1]
        return np.ones(m)/m
    X_C = price_relative_vectors[C]
    mean_returns = np.mean(X_C, axis=0)
    cov_matrix = np.cov(X_C, rowvar=False)

    def objective(b):
        return -np.dot(b, mean_returns) + lambda_* b.T.dot(cov_matrix).dot(b)

    cons = ({'type':'eq','fun':lambda b: np.sum(b)-1})
    bounds = [(0,1)] * price_relative_vectors.shape[1]
    b_init = np.ones(price_relative_vectors.shape[1])/price_relative_vectors.shape[1]
    result = minimize(objective, b_init, method='SLSQP', bounds=bounds, constraints=cons)
    return result.x

def pattern_matching_portfolio_master(b, price_relative_vectors, methods=None, w=4, threshold=0.2, lambda_=0.5, num_neighbors=3, rho=0.7):
    """
    Master function for pattern matching portfolio strategies.
    """
        
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b
    
    for t in range(1, T):
        try:
            if t >= w:
                # Extract method-specific parameters
                ss_params = {}
                if methods['sample_selection'].__name__ == 'kernel_based_selection':
                    ss_params['threshold'] = threshold
                elif methods['sample_selection'].__name__ == 'nearest_neighbor_selection':
                    ss_params['num_neighbors'] = num_neighbors
                elif methods['sample_selection'].__name__ == 'correlation_based_selection':
                    ss_params['rho'] = rho
                
                C_t = methods['sample_selection'](price_relative_vectors[:t], w=w, **ss_params)
            else:
                C_t = []
            
            # Extract portfolio optimization parameters
            po_params = {}
            if methods['portfolio_optimization'].__name__ == 'markowitz_portfolio':
                po_params['lambda_'] = lambda_
            
            b_t = methods['portfolio_optimization'](C_t, price_relative_vectors[:t], **po_params)
            
            # Validate portfolio weights
            if np.any(np.isnan(b_t)):
                b_t = np.ones(N) / N
            elif not np.isclose(np.sum(b_t), 1.0, rtol=1e-5):
                b_t = b_t / np.sum(b_t)
            
            b_n[t] = b_t
            
        except Exception as e:
            b_n[t] = np.ones(N) / N  # Fallback to equal weights
    
    return b_n


def aggregation_algorithm_generalized(b, price_relative_vectors, learning_rate=0.005, gamma=0.3):
    epsilon = 1e-15  # constant for numerical stability
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))
    b_n[0] = b
    expert_weights = np.ones(N) / N

    for t in range(T):
        expert_weights /= np.sum(expert_weights)
        b_n[t] = expert_weights
        if t < T - 1:
            x_t = price_relative_vectors[t]
            losses = -np.log(x_t + epsilon)
            expert_weights *= np.exp(-learning_rate * losses)
            # Mixing step: blend updated weights with a uniform distribution
            expert_weights = (1 - gamma) * expert_weights + gamma * (np.ones(N) / N)
    return b_n


def ons_single_step(current_portfolio, x_t, A, eta=0.1):
    """Helper function for ONS updates with improved numeric stability"""
    port_return = np.dot(current_portfolio, x_t)
    # Add stability constant to prevent division by zero
    port_return = np.maximum(port_return, 1e-10)
    
    grad = -x_t / port_return
    A += np.outer(grad, grad)
    # Add stability constant to diagonal before inversion
    A_inv = np.linalg.inv(A + np.eye(len(x_t)) * 1e-8)
    b_next = current_portfolio - (1.0 / eta) * A_inv.dot(grad)
    b_next = project_to_simplex(b_next)
    return b_next, A


class ONSExpert:
    def __init__(self, b_init, start_time, N, delta=1e-2):
        self.b_current = b_init.copy()
        self.start_time = start_time
        self.N = N
        self.A = np.eye(N) * delta

    def update(self, t, price_relative_vectors, eta=0.1):
        """
        Update the expert from time t to t+1 using a single-step ONS logic.
        """
        x_t = price_relative_vectors[t]
        self.b_current, self.A = ons_single_step(self.b_current, x_t, self.A, eta=eta)

    def get_portfolio(self):
        return self.b_current


def meta_weighted_majority(expert_portfolios, meta_weights, x_t, learning_rate=0.5):
    """Weighted majority with numeric stability improvements"""
    M, N = expert_portfolios.shape
    # Add small constant for numeric stability
    expert_returns = np.maximum(np.einsum('mn,n->m', expert_portfolios, x_t), 1e-10)
    losses = -np.log(expert_returns)
    
    # Compute weights with numeric stability
    weights = meta_weights * np.exp(-learning_rate * losses)
    sum_weights = np.sum(weights)
    if sum_weights > 1e-10:
        new_weights = weights / sum_weights
    else:
        new_weights = np.ones_like(weights) / len(weights)
    return new_weights


def follow_the_leading_history(b_init, price_relative_vectors, eta=0.35, learning_rate=0.07, drop_threshold=0.55):
    """
    Spawns a new ONS expert at each time step t, uses Weighted Majority to 
    combine them, and drops underperforming experts. Uses parallel processing
    for expert updates.
    """
    T, N = price_relative_vectors.shape
    b_n = np.zeros((T, N))

    experts = []
    meta_weights = np.array([])

    def update_expert(expert, t, data, eta):
        expert.update(t, data, eta=eta)
        return expert

    for t in range(T):
        # Spawn a new expert at time t
        new_expert = ONSExpert(b_init, start_time=t, N=N, delta=1e-2)
        experts.append(new_expert)

        # Expand meta_weights to include the new expert
        if len(meta_weights) == 0:
            meta_weights = np.array([1.0])
        else:
            meta_weights = np.append(meta_weights, [1.0])
            meta_weights /= np.sum(meta_weights)

        # Combine the current portfolios of all experts
        expert_portfolios = np.array([exp.get_portfolio() for exp in experts])
        meta_portfolio = np.dot(meta_weights, expert_portfolios)
        meta_portfolio /= np.sum(meta_portfolio)
        b_n[t] = meta_portfolio

        # After we've decided on b_n[t], we see the actual price relative x_t and update
        if t < T - 1:
            x_t = price_relative_vectors[t]
            meta_weights = meta_weighted_majority(expert_portfolios, meta_weights, x_t, learning_rate)
            
            # Parallel update of experts
            updated_experts = [update_expert(expert, t, price_relative_vectors, eta) for expert in experts]
            experts = updated_experts
            
            # Drop experts below threshold
            active_idxs = np.where(meta_weights >= drop_threshold)[0]
            if len(active_idxs) == 0 and len(meta_weights) > 0:
                active_idxs = np.array([np.argmax(meta_weights)])
            experts = [experts[i] for i in active_idxs]
            meta_weights = meta_weights[active_idxs]
            if meta_weights.sum() > 0:
                meta_weights /= meta_weights.sum()
            else:
                meta_weights = np.ones(len(experts)) / len(experts)

    return b_n

