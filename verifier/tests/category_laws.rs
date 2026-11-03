//! Sanity-checks the verification engine's own algebra: `compose` must be
//! associative and `Identity` must be neutral, for any morphisms built from
//! it. This checks the checker's logic, not any particular run's data.

use proptest::prelude::*;
use qa_verifier::category::{compose, Identity, Morphism};

#[derive(Clone, Copy)]
struct AddN(i64);

impl Morphism<i64, i64> for AddN {
    fn apply(&self, a: &i64) -> i64 {
        a + self.0
    }
}

#[derive(Clone, Copy)]
struct MulN(i64);

impl Morphism<i64, i64> for MulN {
    fn apply(&self, a: &i64) -> i64 {
        a * self.0
    }
}

proptest! {
    #[test]
    fn compose_is_associative(x in -1000i64..1000, a in -10i64..10, b in -10i64..10, c in -10i64..10) {
        let f = AddN(a);
        let g = MulN(b);
        let h = AddN(c);

        let left = compose(compose(f, g), h).apply(&x);
        let right = compose(f, compose(g, h)).apply(&x);
        prop_assert_eq!(left, right);
    }

    #[test]
    fn identity_is_neutral_on_both_sides(x in -1000i64..1000, a in -10i64..10) {
        let f = AddN(a);

        let left = compose(Identity, f).apply(&x);
        let right = compose(f, Identity).apply(&x);
        prop_assert_eq!(left, x + a);
        prop_assert_eq!(right, x + a);
    }
}
