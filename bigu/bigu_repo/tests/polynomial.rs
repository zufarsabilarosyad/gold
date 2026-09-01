use std::str::FromStr;

use bigu::poly::Poly;
use bigu::wire::{self, Encoding};
use bigu::{BigI, BigQ, Error};

fn bi(n: i64) -> BigI {
    BigI::from(n)
}

fn bq(n: i64, d: i64) -> BigQ {
    BigQ::new(BigI::from(n), BigI::from(d)).unwrap()
}

#[test]
fn polynomial_canonical_form_and_constructors() {
    let p_zero: Poly<BigI> = Poly::zero();
    assert!(p_zero.is_zero());
    assert!(!p_zero.is_one());
    assert!(p_zero.is_constant());
    assert_eq!(p_zero.degree(), None);
    assert_eq!(p_zero.leading_coeff(), None);
    assert_eq!(p_zero.coeffs(), &[]);

    let p_one: Poly<BigI> = Poly::one();
    assert!(!p_one.is_zero());
    assert!(p_one.is_one());
    assert!(p_one.is_constant());
    assert_eq!(p_one.degree(), Some(0));
    assert_eq!(p_one.leading_coeff(), Some(&bi(1)));
    assert_eq!(p_one.coeffs(), &[bi(1)]);

    let p_x: Poly<BigI> = Poly::x();
    assert_eq!(p_x.degree(), Some(1));
    assert_eq!(p_x.leading_coeff(), Some(&bi(1)));
    assert_eq!(p_x.coeffs(), &[bi(0), bi(1)]);

    // Trailing zeros are stripped
    let p_strip = Poly::new(vec![bi(5), bi(0), bi(3), bi(0), bi(0)]);
    assert_eq!(p_strip.degree(), Some(2));
    assert_eq!(p_strip.leading_coeff(), Some(&bi(3)));
    assert_eq!(p_strip.coeff(0), Some(&bi(5)));
    assert_eq!(p_strip.coeff(1), Some(&bi(0)));
    assert_eq!(p_strip.coeff(2), Some(&bi(3)));
    assert_eq!(p_strip.coeff(3), None);

    let p_all_zeros = Poly::new(vec![bi(0), bi(0), bi(0)]);
    assert!(p_all_zeros.is_zero());
    assert_eq!(p_all_zeros.degree(), None);

    let p_mono = Poly::from_monomial(4, bi(7));
    assert_eq!(p_mono.degree(), Some(4));
    assert_eq!(p_mono.leading_coeff(), Some(&bi(7)));
    assert_eq!(p_mono.coeff(4), Some(&bi(7)));
    assert_eq!(p_mono.coeff(3), Some(&bi(0)));

    let p_mono_zero = Poly::from_monomial(5, bi(0));
    assert!(p_mono_zero.is_zero());
    assert_eq!(p_mono_zero.degree(), None);

    let from_slice = Poly::from_coeffs(&[bi(1), bi(2), bi(3)]);
    assert_eq!(from_slice.coeffs(), &[bi(1), bi(2), bi(3)]);
    assert_eq!(from_slice.into_coeffs(), vec![bi(1), bi(2), bi(3)]);
}

#[test]
fn polynomial_addition_and_subtraction_identities() {
    let p1 = Poly::new(vec![bi(1), bi(2), bi(3)]);
    let p2 = Poly::new(vec![bi(4), bi(-2), bi(5), bi(6)]);

    let sum = &p1 + &p2;
    assert_eq!(sum.coeffs(), &[bi(5), bi(0), bi(8), bi(6)]);

    let diff = &p1 - &p2;
    assert_eq!(diff.coeffs(), &[bi(-3), bi(4), bi(-2), bi(-6)]);

    // Commutativity: p1 + p2 == p2 + p1
    assert_eq!(&p1 + &p2, &p2 + &p1);

    // Identity: p + 0 == p
    assert_eq!(&p1 + &Poly::zero(), p1);
    assert_eq!(&p1 - &Poly::zero(), p1);

    // Self cancellation: p - p == 0
    let zero = &p1 - &p1;
    assert!(zero.is_zero());
    assert_eq!(zero.degree(), None);

    // Negation
    let neg_p1 = -&p1;
    assert_eq!(neg_p1.coeffs(), &[bi(-1), bi(-2), bi(-3)]);
    assert_eq!(&p1 + &neg_p1, Poly::zero());

    // By-value addition, subtraction, and negation
    assert_eq!(p1.clone() + p2.clone(), sum);
    assert_eq!(p1.clone() - p2.clone(), diff);
    assert_eq!(-p1.clone(), neg_p1);

    // BigQ arithmetic
    let q1 = Poly::new(vec![bq(1, 2), bq(2, 3), bq(-1, 5)]);
    let q2 = Poly::new(vec![bq(1, 4), bq(-1, 3), bq(3, 10), bq(7, 8)]);
    let q_sum = &q1 + &q2;
    assert_eq!(q_sum.coeffs(), &[bq(3, 4), bq(1, 3), bq(1, 10), bq(7, 8)]);
    assert_eq!(q1.clone() + q2.clone(), q_sum);

    let q_diff = &q1 - &q2;
    assert_eq!(q_diff.coeffs(), &[bq(1, 4), bq(1, 1), bq(-1, 2), bq(-7, 8)]);
    assert_eq!(q1.clone() - q2.clone(), q_diff);

    let q_neg = -&q1;
    assert_eq!(q_neg.coeffs(), &[bq(-1, 2), bq(-2, 3), bq(1, 5)]);
    assert_eq!(-q1.clone(), q_neg);
}

#[test]
fn polynomial_multiplication_schoolbook_and_karatsuba() {
    // (2x + 3)(4x^2 - 5x + 1) = 8x^3 - 10x^2 + 2x + 12x^2 - 15x + 3 = 8x^3 + 2x^2 - 13x + 3
    let p1 = Poly::new(vec![bi(3), bi(2)]);
    let p2 = Poly::new(vec![bi(1), bi(-5), bi(4)]);
    let prod = &p1 * &p2;
    assert_eq!(prod.coeffs(), &[bi(3), bi(-13), bi(2), bi(8)]);

    // By-value multiplication
    assert_eq!(p1.clone() * p2.clone(), prod);

    // Multiplication commutativity: p1 * p2 == p2 * p1
    assert_eq!(&p1 * &p2, &p2 * &p1);

    // Multiplication by zero
    assert_eq!(&p1 * &Poly::zero(), Poly::zero());
    assert_eq!(&Poly::zero() * &p2, Poly::zero());

    // Multiplication by one
    assert_eq!(&p1 * &Poly::one(), p1);

    // High degree polynomials (> 16 coefficients) strictly triggering Karatsuba multiplication
    let mut large_a = vec![bi(0); 24];
    let mut large_b = vec![bi(0); 24];
    for i in 0..24 {
        large_a[i] = bi(i as i64 + 1);
        large_b[i] = bi((24 - i) as i64);
    }
    let pa = Poly::new(large_a.clone());
    let pb = Poly::new(large_b.clone());
    let pc = &pa * &pb;
    assert_eq!(pc.degree(), Some(46));

    // Cross-validate against direct schoolbook multiplication formula
    let mut expected_coeffs = vec![bi(0); 47];
    for i in 0..24 {
        for j in 0..24 {
            expected_coeffs[i + j] = &expected_coeffs[i + j] + &(&large_a[i] * &large_b[j]);
        }
    }
    assert_eq!(pc.coeffs(), expected_coeffs.as_slice());

    // Algebraic identity: (x^16 - 1) * (x^16 + 1) = x^32 - 1
    let mut xm16 = vec![bi(0); 17];
    xm16[0] = bi(-1);
    xm16[16] = bi(1);
    let mut xp16 = vec![bi(0); 17];
    xp16[0] = bi(1);
    xp16[16] = bi(1);
    let px_m16 = Poly::new(xm16);
    let px_p16 = Poly::new(xp16);
    let px_prod = &px_m16 * &px_p16;
    let mut expected_32 = vec![bi(0); 33];
    expected_32[0] = bi(-1);
    expected_32[32] = bi(1);
    assert_eq!(px_prod.coeffs(), expected_32.as_slice());

    // Homomorphism check: (A * B)(x0) == A(x0) * B(x0)
    let qa = Poly::new(large_a.iter().map(|c| BigQ::from(c.clone())).collect());
    let qb = Poly::new(large_b.iter().map(|c| BigQ::from(c.clone())).collect());
    let qc = &qa * &qb;
    let eval_pt = bq(3, 2);
    let val_prod = qc.eval(&eval_pt);
    let val_a = qa.eval(&eval_pt);
    let val_b = qb.eval(&eval_pt);
    assert_eq!(val_prod, &val_a * &val_b);
}

#[test]
fn polynomial_euclidean_division_exact() {
    // A(x) = x^3 - 2x^2 - 4, B(x) = x - 3
    // x^3 - 2x^2 - 4 = (x^2 + x + 3)(x - 3) + 5
    let a = Poly::new(vec![bq(-4, 1), bq(0, 1), bq(-2, 1), bq(1, 1)]);
    let b = Poly::new(vec![bq(-3, 1), bq(1, 1)]);

    let (q, r) = a.div_rem(&b).unwrap();
    assert_eq!(q.coeffs(), &[bq(3, 1), bq(1, 1), bq(1, 1)]);
    assert_eq!(r.coeffs(), &[bq(5, 1)]);

    // Verify A == Q * B + R
    assert_eq!(&(&q * &b) + &r, a);

    // Division by zero
    assert_eq!(a.div_rem(&Poly::zero()), Err(Error::DivByZero));

    // When deg(A) < deg(B)
    let (q_small, r_small) = b.div_rem(&a).unwrap();
    assert!(q_small.is_zero());
    assert_eq!(r_small, b);

    // Exact division with zero remainder: (x^2 - 1) / (x - 1) = x + 1
    let num = Poly::new(vec![bq(-1, 1), bq(0, 1), bq(1, 1)]);
    let den = Poly::new(vec![bq(-1, 1), bq(1, 1)]);
    let (q_exact, r_exact) = num.div_rem(&den).unwrap();
    assert_eq!(q_exact.coeffs(), &[bq(1, 1), bq(1, 1)]);
    assert!(r_exact.is_zero());

    // Higher degree division
    let h_a = Poly::new(vec![bq(7, 1), bq(-1, 1), bq(1, 1), bq(-3, 1), bq(2, 1), bq(1, 1)]);
    let h_b = Poly::new(vec![bq(1, 1), bq(2, 1), bq(1, 1)]);
    let (hq, hr) = h_a.div_rem(&h_b).unwrap();
    assert_eq!(&(&hq * &h_b) + &hr, h_a);
    assert!(hr.degree().unwrap_or(0) < h_b.degree().unwrap());
}

#[test]
fn polynomial_gcd_monic_and_coprime() {
    // P = (x - 1)^2 * (x + 2) = x^3 - 3x + 2
    // Q = (x - 1) * (x + 3) = x^2 + 2x - 3
    // gcd(P, Q) should be monic (x - 1)
    let p = Poly::new(vec![bq(2, 1), bq(-3, 1), bq(0, 1), bq(1, 1)]);
    let q = Poly::new(vec![bq(-3, 1), bq(2, 1), bq(1, 1)]);

    let g = p.gcd(&q);
    assert_eq!(g.coeffs(), &[bq(-1, 1), bq(1, 1)]);

    // Coprime polynomials: x^2 + 1 and x - 2 -> gcd = 1
    let c1 = Poly::new(vec![bq(1, 1), bq(0, 1), bq(1, 1)]);
    let c2 = Poly::new(vec![bq(-2, 1), bq(1, 1)]);
    assert_eq!(c1.gcd(&c2), Poly::one());

    // GCD with zero
    assert_eq!(p.gcd(&Poly::zero()), p.to_monic());
    assert_eq!(Poly::zero().gcd(&p), p.to_monic());

    // Monic scaling check
    let non_monic = Poly::new(vec![bq(6, 1), bq(9, 1), bq(3, 1)]); // 3x^2 + 9x + 6 = 3(x+1)(x+2)
    assert_eq!(non_monic.to_monic().coeffs(), &[bq(2, 1), bq(3, 1), bq(1, 1)]);
}

#[test]
fn polynomial_horner_evaluation() {
    // P(x) = 2x^3 - 6x^2 + 2x - 1
    let p = Poly::new(vec![bq(-1, 1), bq(2, 1), bq(-6, 1), bq(2, 1)]);
    assert_eq!(p.eval(&bq(3, 1)), bq(5, 1));
    assert_eq!(p.eval(&bq(0, 1)), bq(-1, 1));
    assert_eq!(p.eval(&bq(-1, 1)), bq(-11, 1));
    assert_eq!(p.eval(&bq(1, 2)), bq(-5, 4));

    let p_zero = Poly::<BigQ>::zero();
    assert_eq!(p_zero.eval(&bq(10, 1)), bq(0, 1));

    let p_const = Poly::new(vec![bq(42, 1)]);
    assert_eq!(p_const.eval(&bq(-100, 1)), bq(42, 1));
}

#[test]
fn polynomial_composition_properties() {
    // P(x) = x^2 - 1, Q(x) = 2x + 3
    // P(Q(x)) = (2x + 3)^2 - 1 = 4x^2 + 12x + 8
    let p = Poly::new(vec![bq(-1, 1), bq(0, 1), bq(1, 1)]);
    let q = Poly::new(vec![bq(3, 1), bq(2, 1)]);
    let composed = p.compose(&q);
    assert_eq!(composed.coeffs(), &[bq(8, 1), bq(12, 1), bq(4, 1)]);

    // P(x) composed with x is P(x)
    assert_eq!(p.compose(&Poly::x()), p);

    // P(x) composed with constant c is constant P(c)
    let c = Poly::new(vec![bq(5, 1)]);
    let eval_composed = p.compose(&c);
    assert_eq!(eval_composed.coeffs(), &[bq(24, 1)]);
}

#[test]
fn polynomial_derivative_and_integral() {
    // P(x) = 4x^3 - 3x^2 + 5x - 7
    let p = Poly::new(vec![bq(-7, 1), bq(5, 1), bq(-3, 1), bq(4, 1)]);
    let dp = p.derivative();
    assert_eq!(dp.coeffs(), &[bq(5, 1), bq(-6, 1), bq(12, 1)]);

    // Integral of P'(x) should have same higher terms with constant 0
    let int_dp = dp.integral();
    assert_eq!(int_dp.coeffs(), &[bq(0, 1), bq(5, 1), bq(-3, 1), bq(4, 1)]);

    // Fundamental theorem: (int P dx)' == P
    assert_eq!(p.integral().derivative(), p);

    // Linearity: (P + Q)' == P' + Q'
    let q = Poly::new(vec![bq(1, 1), bq(2, 1), bq(3, 1)]);
    assert_eq!((&p + &q).derivative(), &p.derivative() + &q.derivative());

    // Product rule: (P * Q)' == P' * Q + P * Q'
    let lhs = (&p * &q).derivative();
    let rhs = &(&p.derivative() * &q) + &(&p * &q.derivative());
    assert_eq!(lhs, rhs);

    // Derivative of constant is zero
    let c = Poly::new(vec![bq(42, 1)]);
    assert_eq!(c.derivative(), Poly::zero());
}

#[test]
fn polynomial_square_free_factorization_yun() {
    // P(x) = (x - 1)^3 * (x + 2)^2
    let p = Poly::new(vec![
        bq(-4, 1),
        bq(8, 1),
        bq(-1, 1),
        bq(-5, 1),
        bq(1, 1),
        bq(1, 1),
    ]);

    let factors = p.square_free_factorization();
    assert_eq!(factors.len(), 2);
    let f1 = Poly::new(vec![bq(2, 1), bq(1, 1)]);
    let f2 = Poly::new(vec![bq(-1, 1), bq(1, 1)]);

    assert!(factors.contains(&(f1, 2)));
    assert!(factors.contains(&(f2, 3)));

    // Already square-free polynomial
    let sf = Poly::new(vec![bq(-2, 1), bq(0, 1), bq(1, 1)]); // x^2 - 2
    let sf_factors = sf.square_free_factorization();
    assert_eq!(sf_factors.len(), 1);
    assert_eq!(sf_factors[0], (sf.to_monic(), 1));

    // Multiple factors with varying multiplicities: (x - 3)^1 * (x + 1)^4
    let xm3 = Poly::new(vec![bq(-3, 1), bq(1, 1)]);
    let xp1 = Poly::new(vec![bq(1, 1), bq(1, 1)]);
    let p_multi = &(&(&(&xm3 * &xp1) * &xp1) * &xp1) * &xp1;
    let m_factors = p_multi.square_free_factorization();
    assert_eq!(m_factors.len(), 2);
    assert!(m_factors.contains(&(xm3, 1)));
    assert!(m_factors.contains(&(xp1, 4)));
}

#[test]
fn polynomial_pseudo_division_and_subresultant_gcd() {
    // A(x) = 3x^3 + x^2 + x - 2, B(x) = 2x^2 - 3x + 1
    let a = Poly::new(vec![bi(-2), bi(1), bi(1), bi(3)]);
    let b = Poly::new(vec![bi(1), bi(-3), bi(2)]);

    let (q, r, mult, delta) = a.pseudo_div_rem(&b).unwrap();
    assert_eq!(delta, 2);
    assert_eq!(mult, bi(4));
    let left = Poly::new(a.coeffs().iter().map(|c| c * &bi(4)).collect());
    let right = &(&q * &b) + &r;
    assert_eq!(left, right);

    // Content and primitive part
    let non_prim = Poly::new(vec![bi(6), bi(-12), bi(18)]);
    assert_eq!(non_prim.content(), bi(6));
    assert_eq!(non_prim.primitive_part().coeffs(), &[bi(1), bi(-2), bi(3)]);

    // Subresultant PRS GCD with positive leading coefficient
    let p1 = Poly::new(vec![bi(-10), bi(3), bi(1)]);
    let p2 = Poly::new(vec![bi(-2), bi(-3), bi(2)]);
    let gcd = p1.subresultant_gcd(&p2);
    assert_eq!(gcd.coeffs(), &[bi(-2), bi(1)]); // x - 2
    assert!(gcd.leading_coeff().unwrap() > &bi(0));

    // High degree Subresultant PRS fraction-free anti-blowup test
    // Common factor G(x) = x^4 + 3x^3 + 5x^2 + 7x + 11
    let g_common = Poly::new(vec![bi(11), bi(7), bi(5), bi(3), bi(1)]);
    let f1_mult = Poly::new(vec![bi(8), bi(4), bi(2), bi(1)]); // x^3 + 2x^2 + 4x + 8
    let f2_mult = Poly::new(vec![bi(-5), bi(3), bi(-1), bi(2)]); // 2x^3 - x^2 + 3x - 5
    let poly_a = &g_common * &f1_mult;
    let poly_b = &g_common * &f2_mult;

    let computed_gcd = poly_a.subresultant_gcd(&poly_b);
    assert_eq!(computed_gcd, g_common);

    // Pseudo-division of both input polynomials by computed GCD leaves zero remainder in Z[x]
    let (_, r_a, _, _) = poly_a.pseudo_div_rem(&computed_gcd).unwrap();
    let (_, r_b, _, _) = poly_b.pseudo_div_rem(&computed_gcd).unwrap();
    assert!(r_a.is_zero());
    assert!(r_b.is_zero());

    // Non-primitive input polynomials: content(P) = 12, content(Q) = 18
    // P = 12 * (2x + 3)(x - 1) = 24x^2 + 12x - 36
    // Q = 18 * (2x + 3)(3x + 2) = 108x^2 + 234x + 108
    // gcd(P, Q) must be primitive (2x + 3) with content 1 and positive leading coefficient
    let p_non_prim_a = Poly::new(vec![bi(-36), bi(12), bi(24)]);
    let p_non_prim_b = Poly::new(vec![bi(108), bi(234), bi(108)]);
    assert_eq!(p_non_prim_a.content(), bi(12));
    assert_eq!(p_non_prim_b.content(), bi(18));
    let gcd_non_prim = p_non_prim_a.subresultant_gcd(&p_non_prim_b);
    assert_eq!(gcd_non_prim.coeffs(), &[bi(3), bi(2)]); // 2x + 3
    assert_eq!(gcd_non_prim.content(), bi(1));

    // Negative leading coefficient inputs: P = -4(x^2 - 1), Q = -6(x - 1)
    let p_neg_a = Poly::new(vec![bi(4), bi(0), bi(-4)]);
    let p_neg_b = Poly::new(vec![bi(6), bi(-6)]);
    let gcd_neg = p_neg_a.subresultant_gcd(&p_neg_b);
    assert_eq!(gcd_neg.coeffs(), &[bi(-1), bi(1)]); // x - 1
    assert!(gcd_neg.leading_coeff().unwrap() > &bi(0));
    assert_eq!(gcd_neg.content(), bi(1));
}

#[test]
fn polynomial_formatting_and_parsing_roundtrip() {
    let p1 = Poly::new(vec![bi(5), bi(0), bi(-2), bi(3)]);
    assert_eq!(format!("{p1}"), "3x^3 - 2x^2 + 5");

    let p2 = Poly::new(vec![bi(1), bi(0), bi(1)]);
    assert_eq!(format!("{p2}"), "x^2 + 1");

    let p3 = Poly::new(vec![bi(-7)]);
    assert_eq!(format!("{p3}"), "-7");

    let p_zero: Poly<BigI> = Poly::zero();
    assert_eq!(format!("{p_zero}"), "0");

    let p_x: Poly<BigI> = Poly::x();
    assert_eq!(format!("{p_x}"), "x");

    let p_neg_x = -Poly::<BigI>::x();
    assert_eq!(format!("{p_neg_x}"), "-x");

    // Parsing roundtrip
    let parsed1: Poly<BigI> = Poly::from_str("3x^3 - 2x^2 + 5").unwrap();
    assert_eq!(parsed1, p1);

    let parsed2: Poly<BigI> = Poly::from_str("-x^2 + 1").unwrap();
    assert_eq!(parsed2.coeffs(), &[bi(1), bi(0), bi(-1)]);

    let parsed_q: Poly<BigQ> = Poly::from_str("1/2x^2 - 3/4x + 7").unwrap();
    assert_eq!(parsed_q.coeffs(), &[bq(7, 1), bq(-3, 4), bq(1, 2)]);

    let parsed_compact: Poly<BigI> = Poly::from_str("x^4-x^3+x-5").unwrap();
    assert_eq!(parsed_compact.coeffs(), &[bi(-5), bi(1), bi(0), bi(-1), bi(1)]);

    assert!(Poly::<BigI>::from_str("").is_err());
    assert!(Poly::<BigI>::from_str("3x^foo").is_err());
}

#[test]
fn polynomial_wire_encoding_roundtrip() {
    let enc = Encoding::new();
    let p = Poly::new(vec![bi(-5), bi(0), bi(12), bi(100)]);
    let bytes = wire::encode_poly(&enc, &p).unwrap();

    // Verify outer frame header and Kind::Poly byte tag (5)
    let header = wire::frame::peek(&bytes).unwrap();
    assert_eq!(header.kind, wire::Kind::Poly);
    assert_eq!(bytes[3], 5);

    // Verify inner body structure: varint count followed by ascending Signed coefficient frames
    let (head, body) = wire::frame::unframe(&bytes).unwrap();
    assert_eq!(head.kind, wire::Kind::Poly);

    let (count, mut at) = wire::varint::decode_varint(body, body.len() as u64).unwrap();
    assert_eq!(count, 4);

    let expected_coeffs = [bi(-5), bi(0), bi(12), bi(100)];
    let enc_framed = enc.clone().with_frame(true);
    for expected_c in &expected_coeffs {
        let (coeff_head, _) = wire::frame::unframe(&body[at..]).unwrap();
        assert_eq!(coeff_head.kind, wire::Kind::Signed);
        let decoded_c = enc_framed.decode_signed(&body[at..at + coeff_head.total_len()]).unwrap();
        assert_eq!(&decoded_c, expected_c);
        at += coeff_head.total_len();
    }
    assert_eq!(at, body.len());

    // Full roundtrip decode
    let decoded = wire::decode_poly(&enc, &bytes).unwrap();
    assert_eq!(decoded, p);

    // Independent golden wire vector decoding asserting ascending coefficient order
    // Manually construct wire payload with ascending coefficients [1, 2, 3] -> 3x^2 + 2x + 1
    let mut manual_body = wire::varint::encode_varint(3);
    manual_body.extend_from_slice(&enc_framed.encode_signed(&bi(1)).unwrap()); // c_0 = 1
    manual_body.extend_from_slice(&enc_framed.encode_signed(&bi(2)).unwrap()); // c_1 = 2
    manual_body.extend_from_slice(&enc_framed.encode_signed(&bi(3)).unwrap()); // c_2 = 3
    let manual_frame = wire::frame::frame(wire::Kind::Poly, &manual_body);

    let decoded_manual = wire::decode_poly(&enc, &manual_frame).unwrap();
    assert_eq!(decoded_manual.coeffs(), &[bi(1), bi(2), bi(3)]);
    assert_eq!(decoded_manual.coeff(0), Some(&bi(1)));
    assert_eq!(decoded_manual.coeff(1), Some(&bi(2)));
    assert_eq!(decoded_manual.coeff(2), Some(&bi(3)));

    let p_zero: Poly<BigI> = Poly::zero();
    let bytes_zero = wire::encode_poly(&enc, &p_zero).unwrap();
    let header_zero = wire::frame::peek(&bytes_zero).unwrap();
    assert_eq!(header_zero.kind, wire::Kind::Poly);
    assert_eq!(bytes_zero[3], 5);
    let decoded_zero = wire::decode_poly(&enc, &bytes_zero).unwrap();
    assert_eq!(decoded_zero, p_zero);

    // Rejection of mismatched wire frame kind
    let ratio_bytes = wire::frame::encode_ratio(&enc, &bq(3, 4)).unwrap();
    assert!(wire::decode_poly(&enc, &ratio_bytes).is_err());
}

#[test]
fn polynomial_resultant_and_discriminant_identities() {
    // Sylvester matrix resultant: res(x^2 - 2, x^2 - 3) = (2 - 3)^2 = 1
    let p_sqrt2 = Poly::new(vec![bi(-2), bi(0), bi(1)]);
    let p_sqrt3 = Poly::new(vec![bi(-3), bi(0), bi(1)]);
    assert_eq!(p_sqrt2.resultant(&p_sqrt3), bi(1));

    // res(x^2 + 1, x^2 - 1) = (1 - (-1))^2 = 4
    let p_plus1 = Poly::new(vec![bi(1), bi(0), bi(1)]);
    let p_minus1 = Poly::new(vec![bi(-1), bi(0), bi(1)]);
    assert_eq!(p_plus1.resultant(&p_minus1), bi(4));

    // Linear polynomials: res(2x + 3, 4x - 5) = 2*(-5) - 3*4 = -22
    let l1 = Poly::new(vec![bi(3), bi(2)]);
    let l2 = Poly::new(vec![bi(-5), bi(4)]);
    assert_eq!(l1.resultant(&l2), bi(-22));

    // Common factor implies zero resultant: (x - 2)(x + 3) and (x - 2)(x - 5)
    let p_com1 = Poly::new(vec![bi(-6), bi(1), bi(1)]); // x^2 + x - 6
    let p_com2 = Poly::new(vec![bi(10), bi(-7), bi(1)]); // x^2 - 7x + 10
    assert_eq!(p_com1.resultant(&p_com2), bi(0));

    // Zero polynomial resultant is zero
    assert_eq!(p_sqrt2.resultant(&Poly::zero()), bi(0));
    assert_eq!(Poly::zero().resultant(&p_sqrt2), bi(0));

    // Discriminant of quadratic ax^2 + bx + c: b^2 - 4ac
    // 2x^2 + 5x + 3 -> 25 - 24 = 1
    let quad = Poly::new(vec![bi(3), bi(5), bi(2)]);
    assert_eq!(quad.discriminant(), Some(bi(1)));

    // Discriminant of monic cubic x^3 - 7x + 6 (roots 1, 2, -3):
    // (1-2)^2 * (1-(-3))^2 * (2-(-3))^2 = 1 * 16 * 25 = 400
    let cubic = Poly::new(vec![bi(6), bi(-7), bi(0), bi(1)]);
    assert_eq!(cubic.discriminant(), Some(bi(400)));

    // Discriminant of linear polynomial is 1
    let linear = Poly::new(vec![bi(7), bi(3)]);
    assert_eq!(linear.discriminant(), Some(bi(1)));

    // Discriminant of constant or zero polynomial is None
    let constant = Poly::new(vec![bi(42)]);
    assert_eq!(constant.discriminant(), None);
    assert_eq!(Poly::<BigI>::zero().discriminant(), None);
}
