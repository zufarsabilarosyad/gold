Please implement univariate polynomial algebra, resultant algorithms, and exact real algebraic numbers in `bigu::poly`.

For `Poly<T>`, maintain canonical form (trailing zeros stripped; zero polynomial has degree/leading_coeff `None`). Provide `Poly::new(Vec<T>)`, `Poly::from_coeffs(&[T])`, `Poly::from_monomial(usize, T)`, `Poly::zero()`, `Poly::one()`, `Poly::x()`, accessors `coeffs`, `into_coeffs`, `degree`, `leading_coeff`, `coeff`, predicates `is_zero`, `is_one`, `is_constant`, and operators `Add`, `Sub`, `Neg`, `Mul` for both owned and borrowed operands (`Poly<T>` and `&Poly<T>`).

For `Poly<BigQ>`, implement `div_rem` (yielding `Err(Error::DivByZero)` if divisor is zero), `to_monic`, monic `gcd`, Horner `eval`, `compose`, `derivative`, `integral`, Yun `square_free_factorization`, Sturm sequences `sturm_sequence`, `count_sign_variations`, `count_real_roots_between` on `(a, b]`, `cauchy_root_bound`, and `isolate_real_roots(eps)` returning sorted disjoint intervals of width at most `eps` (empty if `eps <= 0`).

For `Poly<BigI>`, implement `content`, `primitive_part`, pseudo-division `pseudo_div_rem` returning `(q, r, mult, delta)` with mult = d^delta, primitive `subresultant_gcd`, `resultant(&self, &Poly<BigI>) -> BigI` via Sylvester matrix determinant, and `discriminant(&self) -> Option<BigI>`.

Implement exact real algebraic numbers `AlgebraicNumber` defined by a square-free integer polynomial $P(x)$ and an isolating rational interval $(a, b]$ with $P(a)P(b) < 0$ (or exact rational). Provide `from_rational(BigQ) -> Self`, `sqrt(BigQ) -> Option<Self>`, `root_of(Poly<BigI>, usize) -> Option<Self>` ($k$-th real root, 0-indexed), accessors `poly(&self) -> &Poly<BigI>`, `interval(&self) -> (BigQ, BigQ)`, `refine(&mut self, eps: &BigQ)` bisecting until width <= eps, `approx(&self, eps: &BigQ) -> BigQ`, operators `Add`, `Sub`, `Neg`, `Mul`, `Div` for both `AlgebraicNumber` and `&AlgebraicNumber`, `PartialEq`, `Eq`, `PartialOrd`, and `Ord`.

Implement `Display` and `FromStr` for polynomials. In `bigu::wire`, implement `encode_poly` and `decode_poly` with `Kind::Poly = 5` framing varint count and ascending coefficient frames.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
