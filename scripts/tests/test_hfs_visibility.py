from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "check_hfs_visibility.py"
SPEC = importlib.util.spec_from_file_location("check_hfs_visibility_tested", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load HFS visibility checker")
visibility = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = visibility
SPEC.loader.exec_module(visibility)


class FakeApi:
    def __init__(self) -> None:
        self.repos = [
            SimpleNamespace(id="BlueSkyXN/dify-all-in-one", type="space", visibility="protected")
        ]
        self.buckets = {
            "BlueSkyXN/hfs-dist": SimpleNamespace(private=True),
            "artifact-owner/hfs-dist": SimpleNamespace(private=True),
        }
        self.variables = {
            "DIFY_ARTIFACT_MANIFEST_HF_URI": SimpleNamespace(
                value="hf://buckets/artifact-owner/hfs-dist/dify-all-in-one/release/manifest.json"
            )
        }
        self.repo_calls: list[tuple[str | None, str | None]] = []
        self.bucket_calls: list[str] = []

    def list_user_repos(self, namespace: str | None = None, *, token: str | None = None):
        self.repo_calls.append((namespace, token))
        return list(self.repos)

    def bucket_info(self, bucket_id: str, *, token: str | None = None):
        del token
        self.bucket_calls.append(bucket_id)
        return self.buckets[bucket_id]

    def get_space_variables(self, _space: str, *, token: str | None = None):
        del token
        return dict(self.variables)


def manifest() -> dict[str, object]:
    return {
        "space": "BlueSkyXN/dify-all-in-one",
        "lane": "artifact",
        "dist_bucket": "hfs-dist",
        "seed_file": "",
        "space_visibility": "protected",
        "bucket_visibility": "private",
    }


class VisibilityContractTests(unittest.TestCase):
    def test_exact_space_type_and_visibility_are_required(self) -> None:
        api = FakeApi()
        api.repos.insert(
            0,
            SimpleNamespace(
                id="BlueSkyXN/dify-all-in-one", type="model", visibility="protected"
            ),
        )
        selected, bucket_ids = visibility.verify_visibility_contract(
            api, manifest(), "token"
        )
        self.assertEqual(selected, "BlueSkyXN/dify-all-in-one")
        self.assertEqual(bucket_ids, {"BlueSkyXN/hfs-dist"})
        self.assertEqual(api.repo_calls, [("BlueSkyXN", "token")])

    def test_private_space_is_not_accepted_as_protected(self) -> None:
        api = FakeApi()
        api.repos[0].visibility = "private"
        with self.assertRaisesRegex(
            visibility.VisibilityContractError, "not Protected"
        ):
            visibility.verify_visibility_contract(api, manifest(), "token")

    def test_missing_exact_space_repo_type_fails_closed(self) -> None:
        api = FakeApi()
        api.repos = [
            SimpleNamespace(
                id="BlueSkyXN/dify-all-in-one", type="model", visibility="protected"
            )
        ]
        with self.assertRaisesRegex(
            visibility.VisibilityContractError, "exact repository ID"
        ):
            visibility.verify_visibility_contract(api, manifest(), "token")

    def test_registered_bucket_must_be_private(self) -> None:
        api = FakeApi()
        api.buckets["BlueSkyXN/hfs-dist"].private = False
        with self.assertRaisesRegex(visibility.VisibilityContractError, "not Private"):
            visibility.verify_visibility_contract(api, manifest(), "token")

    def test_formal_space_variable_bucket_is_also_checked(self) -> None:
        api = FakeApi()
        _, bucket_ids = visibility.verify_visibility_contract(
            api,
            manifest(),
            "token",
            space_variable_uri_names=["DIFY_ARTIFACT_MANIFEST_HF_URI"],
        )
        self.assertEqual(
            bucket_ids,
            {"BlueSkyXN/hfs-dist", "artifact-owner/hfs-dist"},
        )
        self.assertEqual(
            api.bucket_calls,
            ["BlueSkyXN/hfs-dist", "artifact-owner/hfs-dist"],
        )

    def test_bucket_only_mode_does_not_use_space_settings(self) -> None:
        api = FakeApi()
        _, bucket_ids = visibility.verify_visibility_contract(
            api,
            manifest(),
            "token",
            bucket_uris=["hf://buckets/artifact-owner/hfs-dist"],
            check_space=False,
        )
        self.assertFalse(api.repo_calls)
        self.assertEqual(len(bucket_ids), 2)

    def test_bucket_uri_parser_rejects_ambiguous_inputs(self) -> None:
        for uri in (
            "https://huggingface.co/buckets/BlueSkyXN/hfs-dist",
            "hf://buckets/BlueSkyXN/hfs-dist?public=true",
            "hf://buckets/BlueSkyXN%2Fother/hfs-dist",
            "hf://buckets/BlueSkyXN//hfs-dist",
        ):
            with self.subTest(uri=uri), self.assertRaises(
                visibility.VisibilityContractError
            ):
                visibility.bucket_id_from_uri(uri)

    def test_manifest_visibility_contract_is_not_inferred(self) -> None:
        api = FakeApi()
        for key, value in (
            ("space_visibility", "private"),
            ("bucket_visibility", "public"),
        ):
            data = manifest()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(
                visibility.VisibilityContractError
            ):
                visibility.verify_visibility_contract(api, data, "token")


if __name__ == "__main__":
    unittest.main()
