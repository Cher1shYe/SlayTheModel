"""Behavioural tests for SpireFormer's masked Set Transformer blocks."""

from __future__ import annotations

import unittest

import torch

from spireformer.set_transformer import ISAB, MAB, PMA, SAB, SetEncoder


class SetTransformerTests(unittest.TestCase):
    def setUp(self) -> None:
        torch.manual_seed(1729)
        self.x = torch.randn(2, 5, 6)
        self.padding_mask = torch.tensor(
            [
                [False, False, False, True, True],
                [False, False, False, False, True],
            ]
        )
        self.permutation = torch.tensor([2, 4, 0, 3, 1])

    def assertTensorClose(self, actual: torch.Tensor, expected: torch.Tensor) -> None:
        torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-6)

    def test_mab_is_equivariant_to_queries_and_invariant_to_key_order(self) -> None:
        block = MAB(6, 7, 8, 2).eval()
        query = torch.randn(2, 4, 6)
        key = torch.randn(2, 5, 7)
        query_mask = torch.tensor(
            [[False, False, True, True], [False, False, False, True]]
        )
        key_mask = self.padding_mask
        query_permutation = torch.tensor([2, 0, 3, 1])

        baseline = block(
            query,
            key,
            query_padding_mask=query_mask,
            key_padding_mask=key_mask,
        )
        permuted = block(
            query[:, query_permutation],
            key[:, self.permutation],
            query_padding_mask=query_mask[:, query_permutation],
            key_padding_mask=key_mask[:, self.permutation],
        )

        self.assertTensorClose(permuted, baseline[:, query_permutation])
        self.assertTrue(
            torch.equal(baseline[query_mask], torch.zeros_like(baseline[query_mask]))
        )

    def test_sab_is_permutation_equivariant(self) -> None:
        block = SAB(6, 8, 2).eval()

        baseline = block(self.x, self.padding_mask)
        permuted = block(
            self.x[:, self.permutation],
            self.padding_mask[:, self.permutation],
        )

        self.assertTensorClose(permuted, baseline[:, self.permutation])

    def test_isab_is_permutation_equivariant(self) -> None:
        block = ISAB(6, 8, 2, num_inducing_points=3).eval()

        baseline = block(self.x, self.padding_mask)
        permuted = block(
            self.x[:, self.permutation],
            self.padding_mask[:, self.permutation],
        )

        self.assertTensorClose(permuted, baseline[:, self.permutation])

    def test_pma_is_permutation_invariant(self) -> None:
        pooling = PMA(6, 8, 2, num_seeds=2).eval()

        baseline = pooling(self.x, self.padding_mask)
        permuted = pooling(
            self.x[:, self.permutation],
            self.padding_mask[:, self.permutation],
        )

        self.assertEqual(tuple(baseline.shape), (2, 2, 8))
        self.assertTensorClose(permuted, baseline)

    def test_set_encoder_exposes_equivariant_entities_and_invariant_summary(
        self,
    ) -> None:
        encoder = SetEncoder(
            6,
            8,
            2,
            num_layers=2,
            num_inducing_points=3,
            num_seeds=1,
        ).eval()

        entities, summary = encoder.forward_with_entities(self.x, self.padding_mask)
        permuted_entities = encoder.encode_entities(
            self.x[:, self.permutation],
            self.padding_mask[:, self.permutation],
        )
        permuted_summary = encoder(
            self.x[:, self.permutation],
            self.padding_mask[:, self.permutation],
        )

        self.assertEqual(tuple(entities.shape), (2, 5, 8))
        self.assertEqual(tuple(summary.shape), (2, 1, 8))
        self.assertTensorClose(permuted_entities, entities[:, self.permutation])
        self.assertTensorClose(permuted_summary, summary)

    def test_masked_values_cannot_change_the_summary(self) -> None:
        encoder = SetEncoder(
            6,
            8,
            2,
            num_layers=2,
            num_inducing_points=None,
        ).eval()
        changed_padding = self.x.clone()
        changed_padding[self.padding_mask] = (
            torch.randn_like(changed_padding[self.padding_mask]) * 1_000.0
        )

        baseline = encoder(self.x, self.padding_mask)
        changed = encoder(changed_padding, self.padding_mask)

        self.assertTensorClose(changed, baseline)

    def test_fully_padded_sets_are_finite_and_ignore_slot_contents(self) -> None:
        pooling = PMA(6, 8, 2).eval()
        empty_mask = torch.ones(2, 3, dtype=torch.bool)
        first_slots = torch.randn(2, 3, 6)
        other_slots = torch.randn(2, 3, 6) * 10_000.0

        first = pooling(first_slots, empty_mask)
        other = pooling(other_slots, empty_mask)

        self.assertTrue(bool(torch.isfinite(first).all()))
        self.assertTensorClose(first, other)

    def test_strict_shape_and_mask_validation(self) -> None:
        block = SAB(6, 8, 2)

        with self.assertRaisesRegex(ValueError, "shape"):
            block(torch.randn(2, 6))
        with self.assertRaisesRegex(ValueError, "feature dimension"):
            block(torch.randn(2, 3, 5))
        with self.assertRaisesRegex(TypeError, "torch.bool"):
            block(torch.randn(2, 3, 6), torch.zeros(2, 3))
        with self.assertRaisesRegex(ValueError, "shape"):
            block(
                torch.randn(2, 3, 6),
                torch.zeros(2, 4, dtype=torch.bool),
            )
        with self.assertRaisesRegex(ValueError, "at least one tensor slot"):
            block(torch.empty(2, 0, 6))

    def test_constructor_validation_is_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "divisible"):
            MAB(6, 6, 7, 2)
        with self.assertRaisesRegex(ValueError, "num_layers"):
            SetEncoder(6, 8, 2, num_layers=0)
        with self.assertRaisesRegex(ValueError, "num_inducing_points"):
            ISAB(6, 8, 2, num_inducing_points=0)


if __name__ == "__main__":
    unittest.main()
