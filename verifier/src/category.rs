//! Minimal category-theoretic vocabulary used to express pipeline-stage
//! contracts: objects are typed pipeline-stage snapshots, morphisms are the
//! declared stage-to-stage transformations. This module only carries the
//! algebra (compose/identity); `laws.rs` and `oracle.rs` apply it to real
//! pipeline data.

use std::marker::PhantomData;

/// A morphism between two typed pipeline-stage objects.
pub trait Morphism<A, B> {
    fn apply(&self, a: &A) -> B;
}

/// The composite of `f: A -> B` followed by `g: B -> C`. `B` is carried as a
/// `PhantomData` marker purely so the impl below can be coherent -- it's
/// never constructed, only used to pin down which `Morphism` impls apply.
pub struct Composed<F, G, B> {
    f: F,
    g: G,
    _marker: PhantomData<B>,
}

// Manual Clone/Copy impls (rather than `derive`) so they only require `F`
// and `G` to be Clone/Copy -- a derive would also (incorrectly) demand it
// of the unused `B` parameter.
impl<F: Clone, G: Clone, B> Clone for Composed<F, G, B> {
    fn clone(&self) -> Self {
        Composed {
            f: self.f.clone(),
            g: self.g.clone(),
            _marker: PhantomData,
        }
    }
}

impl<F: Copy, G: Copy, B> Copy for Composed<F, G, B> {}

impl<A, B, C, F, G> Morphism<A, C> for Composed<F, G, B>
where
    F: Morphism<A, B>,
    G: Morphism<B, C>,
{
    fn apply(&self, a: &A) -> C {
        self.g.apply(&self.f.apply(a))
    }
}

pub fn compose<A, B, C, F, G>(f: F, g: G) -> Composed<F, G, B>
where
    F: Morphism<A, B>,
    G: Morphism<B, C>,
{
    Composed {
        f,
        g,
        _marker: PhantomData,
    }
}

/// The identity morphism `A -> A`.
#[derive(Debug, Clone, Copy)]
pub struct Identity;

impl<A: Clone> Morphism<A, A> for Identity {
    fn apply(&self, a: &A) -> A {
        a.clone()
    }
}

/// A contract checked between a stage's input and its claimed output -- the
/// concrete stand-in for "this morphism is well-typed". Returns violation
/// messages when `output` doesn't satisfy the contract given `input`.
pub trait Contract<In, Out> {
    fn check(&self, input: &In, output: &Out) -> Vec<String>;
}
