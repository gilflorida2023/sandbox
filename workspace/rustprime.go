use sha2::{Sha256, Digest};
use std::io::Write;

fn main() {
    let limit = 1_000_000;
    let primes = sieve_of_eratosthenes(limit);

    let mut hasher = Sha256::new();
    for &prime in &primes {
        let bytes = prime.to_le_bytes();
        hasher.update(&bytes);
    }

    let result = hasher.finalize();
    let hex_result = format!("{:x}", result);

    print!("{}", hex_result);
    std::io::stdout().flush().unwrap();
}

fn sieve_of_eratosthenes(limit: usize) -> Vec<usize> {
    let mut is_prime = vec![true; limit + 1];
    let mut p = 2;

    while p * p <= limit {
        if is_prime[p] {
            for i in (p * p..=limit).step_by(p) {
                is_prime[i] = false;
            }
        }
        p += 1;
    }

    let mut primes = Vec::new();
    for i in 2..=limit {
        if is_prime[i] {
            primes.push(i);
        }
    }

    primes
}
