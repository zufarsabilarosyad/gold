use bigu::poly::Poly;
use bigu::BigQ;

fn bq(n: i64, d: i64) -> BigQ {
    BigQ::new(bigu::BigI::from(n), bigu::BigI::from(d)).unwrap()
}

#[test]
fn sturm_direct_count_sign_variations() {
    let p0 = Poly::new(vec![bq(-4, 1), bq(0, 1), bq(1, 1)]); // x^2 - 4
    let p1 = Poly::new(vec![bq(0, 1), bq(2, 1)]);            // 2x
    let p2 = Poly::new(vec![bq(4, 1)]);                       // 4
    let seq = [p0, p1, p2];

    // At x = -3: p0(-3) = 5 (+), p1(-3) = -6 (-), p2(-3) = 4 (+) -> 2 sign variations
    assert_eq!(Poly::<BigQ>::count_sign_variations(&seq, &bq(-3, 1)), 2);

    // At x = 0: p0(0) = -4 (-), p1(0) = 0 (0, skipped), p2(0) = 4 (+) -> 1 sign variation
    assert_eq!(Poly::<BigQ>::count_sign_variations(&seq, &bq(0, 1)), 1);

    // At x = 3: p0(3) = 5 (+), p1(3) = 6 (+), p2(3) = 4 (+) -> 0 sign variations
    assert_eq!(Poly::<BigQ>::count_sign_variations(&seq, &bq(3, 1)), 0);

    // Empty sequence
    assert_eq!(Poly::<BigQ>::count_sign_variations(&[], &bq(1, 1)), 0);
}

#[test]
fn sturm_sequence_quadratic_and_cubic() {
    // P(x) = x^2 - 4
    // P_0 = x^2 - 4
    // P_1 = 2x
    // P_2 = -rem(x^2 - 4, 2x) = 4
    let p2 = Poly::new(vec![bq(-4, 1), bq(0, 1), bq(1, 1)]);
    let seq2 = p2.sturm_sequence();
    assert_eq!(seq2.len(), 3);
    assert_eq!(seq2[0].coeffs(), &[bq(-4, 1), bq(0, 1), bq(1, 1)]);
    assert_eq!(seq2[1].coeffs(), &[bq(0, 1), bq(2, 1)]);
    assert_eq!(seq2[2].coeffs(), &[bq(4, 1)]);

    // P(x) = x^3 - 3x + 1
    let p3 = Poly::new(vec![bq(1, 1), bq(-3, 1), bq(0, 1), bq(1, 1)]);
    let seq3 = p3.sturm_sequence();
    assert_eq!(seq3.len(), 4);
    assert_eq!(seq3[0].degree(), Some(3));
    assert_eq!(seq3[1].degree(), Some(2));

    // Linear polynomial Sturm sequence
    let p_lin = Poly::new(vec![bq(-5, 1), bq(2, 1)]);
    let seq_lin = p_lin.sturm_sequence();
    assert_eq!(seq_lin.len(), 2);
    assert_eq!(seq_lin[0].degree(), Some(1));
    assert_eq!(seq_lin[1].degree(), Some(0));
}

#[test]
fn sturm_sign_variations_and_root_counting() {
    // P(x) = x^3 - 3x (roots at -sqrt(3) ~= -1.732, 0, sqrt(3) ~= 1.732)
    let p = Poly::new(vec![bq(0, 1), bq(-3, 1), bq(0, 1), bq(1, 1)]);

    // Between -2 and 2: all 3 roots are in (-2, 2]
    assert_eq!(p.count_real_roots_between(&bq(-2, 1), &bq(2, 1)), 3);

    // Between 0 and 2: roots 0 and sqrt(3) in (0, 2] -> only sqrt(3) in (0, 2], count = 1
    assert_eq!(p.count_real_roots_between(&bq(0, 1), &bq(2, 1)), 1);

    // Between -1 and 1: root 0 in (-1, 1] -> count = 1
    assert_eq!(p.count_real_roots_between(&bq(-1, 1), &bq(1, 1)), 1);

    // Outside: between 2 and 5 -> 0 roots
    assert_eq!(p.count_real_roots_between(&bq(2, 1), &bq(5, 1)), 0);

    // Negative side: between -5 and -2 -> 0 roots
    assert_eq!(p.count_real_roots_between(&bq(-5, 1), &bq(-2, 1)), 0);

    // Negative interval containing -sqrt(3): between -2 and -1 -> 1 root
    assert_eq!(p.count_real_roots_between(&bq(-2, 1), &bq(-1, 1)), 1);

    // Empty or inverted interval
    assert_eq!(p.count_real_roots_between(&bq(2, 1), &bq(1, 1)), 0);
    assert_eq!(p.count_real_roots_between(&bq(2, 1), &bq(2, 1)), 0);
}

#[test]
fn cauchy_root_bound_correctness() {
    // P(x) = x^3 - 6x^2 + 11x - 6 = (x - 1)(x - 2)(x - 3)
    let p = Poly::new(vec![bq(-6, 1), bq(11, 1), bq(-6, 1), bq(1, 1)]);
    let bound = p.cauchy_root_bound();
    assert!(bound >= bq(3, 1));

    // High coefficient polynomial
    let p_large = Poly::new(vec![bq(-1000, 1), bq(0, 1), bq(1, 1)]); // x^2 - 1000
    let b_large = p_large.cauchy_root_bound();
    assert!(b_large >= bq(31, 1));
}

#[test]
fn isolate_real_roots_linear_and_quadratic() {
    // 2x - 5 = 0 -> root = 5/2 = 2.5
    let p_lin = Poly::new(vec![bq(-5, 1), bq(2, 1)]);
    let roots_lin = p_lin.isolate_real_roots(&bq(1, 100));
    assert_eq!(roots_lin.len(), 1);
    let (l, r) = &roots_lin[0];
    assert!(*l <= bq(5, 2) && bq(5, 2) <= *r);
    assert!((r - l) <= bq(1, 100));

    // x^2 - 2 = 0 -> roots +/- sqrt(2) ~= +/- 1.4142
    let p_quad = Poly::new(vec![bq(-2, 1), bq(0, 1), bq(1, 1)]);
    let roots_quad = p_quad.isolate_real_roots(&bq(1, 1000));
    assert_eq!(roots_quad.len(), 2);
    // Root 1 is negative (around -1.414)
    assert!(roots_quad[0].0 < bq(0, 1) && roots_quad[0].1 < bq(0, 1));
    // Root 2 is positive (around +1.414)
    assert!(roots_quad[1].0 > bq(0, 1) && roots_quad[1].1 > bq(0, 1));
    for (l, r) in &roots_quad {
        assert!((r - l) <= bq(1, 1000));
    }
}

#[test]
fn isolate_real_roots_cubic_and_quartic() {
    // Cubic with 3 real roots: x^3 - 3x + 1 = 0
    let p_cubic = Poly::new(vec![bq(1, 1), bq(-3, 1), bq(0, 1), bq(1, 1)]);
    let roots_cubic = p_cubic.isolate_real_roots(&bq(1, 1000));
    assert_eq!(roots_cubic.len(), 3);
    assert!(roots_cubic[0].1 < roots_cubic[1].0);
    assert!(roots_cubic[1].1 < roots_cubic[2].0);

    // Quartic: (x^2 - 2)(x^2 - 5) = x^4 - 7x^2 + 10 = 0 (4 real roots: +/- sqrt(2), +/- sqrt(5))
    let p_quartic = Poly::new(vec![bq(10, 1), bq(0, 1), bq(-7, 1), bq(0, 1), bq(1, 1)]);
    let roots_quartic = p_quartic.isolate_real_roots(&bq(1, 500));
    assert_eq!(roots_quartic.len(), 4);
    for i in 0..3 {
        assert!(roots_quartic[i].1 <= roots_quartic[i + 1].0);
    }
}

#[test]
fn isolate_real_roots_wilkinson_polynomial() {
    // (x - 1)(x - 2)(x - 3)(x - 4) = x^4 - 10x^3 + 35x^2 - 50x + 24
    let p = Poly::new(vec![bq(24, 1), bq(-50, 1), bq(35, 1), bq(-10, 1), bq(1, 1)]);
    let roots = p.isolate_real_roots(&bq(1, 100));
    assert_eq!(roots.len(), 4);

    let expected = [bq(1, 1), bq(2, 1), bq(3, 1), bq(4, 1)];
    for (i, exp) in expected.iter().enumerate() {
        let (l, r) = &roots[i];
        assert!(*l <= *exp && *exp <= *r);
    }
}

#[test]
fn isolate_real_roots_chebyshev_polynomial() {
    // Chebyshev polynomial T_4(x) = 8x^4 - 8x^2 + 1
    let t4 = Poly::new(vec![bq(1, 1), bq(0, 1), bq(-8, 1), bq(0, 1), bq(8, 1)]);
    let roots = t4.isolate_real_roots(&bq(1, 1000));
    assert_eq!(roots.len(), 4);
    // Root 1: ~= -0.92388 (< -0.9)
    assert!(roots[0].1 < bq(-9, 10));
    // Root 2: ~= -0.38268 (in (-0.45, -0.35))
    assert!(roots[1].0 > bq(-45, 100) && roots[1].1 < bq(-35, 100));
    // Root 3: ~= +0.38268 (in (0.35, 0.45))
    assert!(roots[2].0 > bq(35, 100) && roots[2].1 < bq(45, 100));
    // Root 4: ~= +0.92388 (> 0.9)
    assert!(roots[3].0 > bq(9, 10));
}

#[test]
fn isolate_real_roots_no_real_roots() {
    // x^2 + 1 = 0 has no real roots
    let p1 = Poly::new(vec![bq(1, 1), bq(0, 1), bq(1, 1)]);
    assert!(p1.isolate_real_roots(&bq(1, 100)).is_empty());

    // x^4 + 2x^2 + 5 = 0 has no real roots
    let p2 = Poly::new(vec![bq(5, 1), bq(0, 1), bq(2, 1), bq(0, 1), bq(1, 1)]);
    assert!(p2.isolate_real_roots(&bq(1, 100)).is_empty());
}

#[test]
fn isolate_real_roots_with_multiple_roots() {
    // P(x) = (x - 2)^2 * (x + 3)^3 has 2 distinct real roots: -3 and 2.
    let xm2 = Poly::new(vec![bq(-2, 1), bq(1, 1)]);
    let xp3 = Poly::new(vec![bq(3, 1), bq(1, 1)]);
    let p = &(&(&(&xm2 * &xm2) * &xp3) * &xp3) * &xp3;

    let roots = p.isolate_real_roots(&bq(1, 100));
    assert_eq!(roots.len(), 2);
    assert!(roots[0].0 <= bq(-3, 1) && bq(-3, 1) <= roots[0].1);
    assert!(roots[1].0 <= bq(2, 1) && bq(2, 1) <= roots[1].1);
}

#[test]
fn sturm_root_isolation_precision_scaling() {
    let p = Poly::new(vec![bq(-2, 1), bq(0, 1), bq(1, 1)]); // x^2 - 2
    for denom in [10, 100, 1000, 10000] {
        let eps = bq(1, denom);
        let roots = p.isolate_real_roots(&eps);
        assert_eq!(roots.len(), 2);
        for (l, r) in &roots {
            assert!((r - l) <= eps);
        }
    }
}

#[test]
fn sturm_boundary_and_degenerate_cases() {
    let p_zero = Poly::<BigQ>::zero();
    assert!(p_zero.isolate_real_roots(&bq(1, 10)).is_empty());

    let p_const = Poly::new(vec![bq(7, 1)]);
    assert!(p_const.isolate_real_roots(&bq(1, 10)).is_empty());

    let p_neg_eps = Poly::new(vec![bq(-2, 1), bq(1, 1)]);
    assert!(p_neg_eps.isolate_real_roots(&bq(-1, 10)).is_empty());
    assert!(p_neg_eps.isolate_real_roots(&bq(0, 1)).is_empty());
}
