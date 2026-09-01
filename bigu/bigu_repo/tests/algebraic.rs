use bigu::poly::AlgebraicNumber;
use bigu::{BigI, BigQ, Poly};

fn bi(n: i64) -> BigI {
    BigI::from(n)
}

fn bq(n: i64, d: i64) -> BigQ {
    BigQ::new(bi(n), bi(d)).unwrap()
}

#[test]
fn algebraic_number_rational_and_sqrt_constructors() {
    let q = bq(3, 4);
    let alg_q = AlgebraicNumber::from_rational(q.clone());
    assert_eq!(alg_q.interval(), (q.clone(), q.clone()));
    assert_eq!(alg_q.approx(&bq(1, 1000)), q);

    // sqrt(2)
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let approx_sqrt2 = sqrt2.approx(&bq(1, 1000));
    // 1.414 is between 1414/1000 and 1415/1000
    assert!(approx_sqrt2 > bq(141, 100) && approx_sqrt2 < bq(142, 100));

    // sqrt(9/4) = 3/2
    let sqrt_9_4 = AlgebraicNumber::sqrt(bq(9, 4)).unwrap();
    let approx_3_2 = sqrt_9_4.approx(&bq(1, 1000));
    let diff = (&approx_3_2 - &bq(3, 2)).abs();
    assert!(diff < bq(1, 1000));

    // Negative rational has no real square root
    assert!(AlgebraicNumber::sqrt(bq(-1, 1)).is_none());

    // sqrt(0) = 0
    let sqrt0 = AlgebraicNumber::sqrt(bq(0, 1)).unwrap();
    assert_eq!(sqrt0.approx(&bq(1, 1000)), bq(0, 1));
}

#[test]
fn algebraic_number_root_of_polynomials() {
    // P(x) = x^3 - 2 (only one real root: 2^(1/3) ~ 1.2599)
    let p_cbrt2 = Poly::new(vec![bi(-2), bi(0), bi(0), bi(1)]);
    let cbrt2 = AlgebraicNumber::root_of(p_cbrt2.clone(), 0).unwrap();
    let approx = cbrt2.approx(&bq(1, 1000));
    assert!(approx > bq(125, 100) && approx < bq(127, 100));

    // Out-of-bounds root index returns None
    assert!(AlgebraicNumber::root_of(p_cbrt2, 1).is_none());

    // P(x) = x^4 - 5x^2 + 4 = (x-2)(x-1)(x+1)(x+2) -> 4 roots: -2, -1, 1, 2
    let p4 = Poly::new(vec![bi(4), bi(0), bi(-5), bi(0), bi(1)]);
    let r0 = AlgebraicNumber::root_of(p4.clone(), 0).unwrap();
    let r1 = AlgebraicNumber::root_of(p4.clone(), 1).unwrap();
    let r2 = AlgebraicNumber::root_of(p4.clone(), 2).unwrap();
    let r3 = AlgebraicNumber::root_of(p4.clone(), 3).unwrap();

    let diff0 = (&r0.approx(&bq(1, 1000)) - &bq(-2, 1)).abs();
    let diff1 = (&r1.approx(&bq(1, 1000)) - &bq(-1, 1)).abs();
    let diff2 = (&r2.approx(&bq(1, 1000)) - &bq(1, 1)).abs();
    let diff3 = (&r3.approx(&bq(1, 1000)) - &bq(2, 1)).abs();
    assert!(diff0 < bq(1, 1000));
    assert!(diff1 < bq(1, 1000));
    assert!(diff2 < bq(1, 1000));
    assert!(diff3 < bq(1, 1000));
}

#[test]
fn algebraic_number_addition_and_subtraction_identities() {
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let sqrt3 = AlgebraicNumber::sqrt(bq(3, 1)).unwrap();

    // Borrowed and owned addition
    let sum = &sqrt2 + &sqrt3;
    let sum_owned = sqrt2.clone() + sqrt3.clone();
    assert_eq!(sum, sum_owned);

    // approx(sqrt2 + sqrt3) ~ 1.414 + 1.732 = 3.146
    let approx_sum = sum.approx(&bq(1, 1000));
    assert!(approx_sum > bq(314, 100) && approx_sum < bq(316, 100));

    // (sqrt2 + sqrt3) - sqrt2 == sqrt3
    let diff_sqrt3 = &sum - &sqrt2;
    assert_eq!(diff_sqrt3, sqrt3);

    // (sqrt2 + sqrt3) - sqrt3 == sqrt2
    let diff_sqrt2 = sum_owned - sqrt3.clone();
    assert_eq!(diff_sqrt2, sqrt2);

    // Negation
    let neg_sqrt2 = -&sqrt2;
    let neg_owned = -sqrt2.clone();
    assert_eq!(neg_sqrt2, neg_owned);
    assert_eq!(&sqrt2 + &neg_sqrt2, AlgebraicNumber::from_rational(bq(0, 1)));
}

#[test]
fn algebraic_number_multiplication_and_division_golden_ratio() {
    // Golden ratio phi = (1 + sqrt(5)) / 2: root of x^2 - x - 1 = 0
    let p_phi = Poly::new(vec![bi(-1), bi(-1), bi(1)]);
    let phi = AlgebraicNumber::root_of(p_phi, 1).unwrap();

    // phi ~ 1.61803
    let approx_phi = phi.approx(&bq(1, 1000));
    assert!(approx_phi > bq(161, 100) && approx_phi < bq(163, 100));

    // phi * (phi - 1) == 1
    let one = AlgebraicNumber::from_rational(bq(1, 1));
    let phi_minus_1 = &phi - &one;
    let prod = &phi * &phi_minus_1;
    assert_eq!(prod, one);

    // 1 / phi == phi - 1
    let inv_phi = &one / &phi;
    assert_eq!(inv_phi, phi_minus_1);

    // sqrt(2) * sqrt(3) == sqrt(6)
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let sqrt3 = AlgebraicNumber::sqrt(bq(3, 1)).unwrap();
    let sqrt6 = AlgebraicNumber::sqrt(bq(6, 1)).unwrap();
    assert_eq!(&sqrt2 * &sqrt3, sqrt6);

    // sqrt(6) / sqrt(2) == sqrt(3)
    assert_eq!(&sqrt6 / &sqrt2, sqrt3);
}

#[test]
fn algebraic_number_nested_radicals_and_minimal_polynomials() {
    // (sqrt(2) + 1)(sqrt(2) - 1) = 2 - 1 = 1
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let one = AlgebraicNumber::from_rational(bq(1, 1));

    let term1 = &sqrt2 + &one;
    let term2 = &sqrt2 - &one;
    let prod = &term1 * &term2;
    assert_eq!(prod, one);

    // sqrt(2) + sqrt(3) has minimal polynomial x^4 - 10x^2 + 1
    let sqrt3 = AlgebraicNumber::sqrt(bq(3, 1)).unwrap();
    let sum = &sqrt2 + &sqrt3;
    let min_p = Poly::new(vec![bi(1), bi(0), bi(-10), bi(0), bi(1)]);
    assert_eq!(sum.poly().subresultant_gcd(&min_p), min_p);
}

#[test]
fn algebraic_number_total_ordering_and_equality() {
    let zero = AlgebraicNumber::from_rational(bq(0, 1));
    let one = AlgebraicNumber::from_rational(bq(1, 1));
    let two = AlgebraicNumber::from_rational(bq(2, 1));
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let sqrt3 = AlgebraicNumber::sqrt(bq(3, 1)).unwrap();
    let sqrt5 = AlgebraicNumber::sqrt(bq(5, 1)).unwrap();

    assert!(zero < one);
    assert!(one < sqrt2);
    assert!(sqrt2 < sqrt3);
    assert!(sqrt3 < two);
    assert!(two < sqrt5);

    // Negative numbers
    let neg_sqrt2 = -&sqrt2;
    assert!(neg_sqrt2 < zero);
    assert!(neg_sqrt2 < sqrt2);

    // Reflexivity & Equality
    assert_eq!(sqrt2, sqrt2);
    let sqrt4 = AlgebraicNumber::sqrt(bq(4, 1)).unwrap();
    assert_eq!(sqrt4, two);
}

#[test]
fn algebraic_number_interval_refinement_and_approximation() {
    let mut sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let eps_wide = bq(1, 10);
    let eps_tight = bq(1, 1000000);

    sqrt2.refine(&eps_wide);
    let (a, b) = sqrt2.interval();
    assert!(&b - &a <= eps_wide);

    sqrt2.refine(&eps_tight);
    let (a2, b2) = sqrt2.interval();
    assert!(&b2 - &a2 <= eps_tight);

    let approx = sqrt2.approx(&eps_tight);
    let approx_sq = &approx * &approx;
    let diff = (&approx_sq - &bq(2, 1)).abs();
    assert!(diff < bq(1, 100000));
}

#[test]
fn algebraic_number_cancellation_and_zero_testing() {
    let sqrt2 = AlgebraicNumber::sqrt(bq(2, 1)).unwrap();
    let zero = AlgebraicNumber::from_rational(bq(0, 1));

    // Self-subtraction
    assert_eq!(&sqrt2 - &sqrt2, zero);

    // sqrt(2) + (-sqrt(2)) == 0
    assert_eq!(&sqrt2 + &(-&sqrt2), zero);

    // Rational cancellation: (3/2) - (3/2) == 0
    let q32 = AlgebraicNumber::from_rational(bq(3, 2));
    assert_eq!(&q32 - &q32, zero);
}

#[test]
fn algebraic_number_cubic_and_quartic_roots() {
    // P(x) = x^3 - 3x + 1 (three distinct real roots)
    let p = Poly::new(vec![bi(1), bi(-3), bi(0), bi(1)]);
    let r0 = AlgebraicNumber::root_of(p.clone(), 0).unwrap();
    let r1 = AlgebraicNumber::root_of(p.clone(), 1).unwrap();
    let r2 = AlgebraicNumber::root_of(p, 2).unwrap();

    assert!(r0 < r1);
    assert!(r1 < r2);

    // Vieta's formulas:
    // Sum of roots = -coeff(2) / coeff(3) = 0
    let sum = &(&r0 + &r1) + &r2;
    assert_eq!(sum, AlgebraicNumber::from_rational(bq(0, 1)));

    // Product of roots = -coeff(0) / coeff(3) = -1
    let prod = &(&r0 * &r1) * &r2;
    assert_eq!(prod, AlgebraicNumber::from_rational(bq(-1, 1)));
}

#[test]
fn algebraic_number_error_cases_and_edge_values() {
    // Zero polynomial root
    assert!(AlgebraicNumber::root_of(Poly::zero(), 0).is_none());

    // Constant polynomial root
    assert!(AlgebraicNumber::root_of(Poly::new(vec![bi(5)]), 0).is_none());

    // Negative square root
    assert!(AlgebraicNumber::sqrt(bq(-7, 3)).is_none());

    // Refinement with zero/negative epsilon leaves interval unchanged
    let mut sqrt3 = AlgebraicNumber::sqrt(bq(3, 1)).unwrap();
    let initial_interval = sqrt3.interval();
    sqrt3.refine(&bq(0, 1));
    assert_eq!(sqrt3.interval(), initial_interval);
    sqrt3.refine(&bq(-1, 1));
    assert_eq!(sqrt3.interval(), initial_interval);
}
