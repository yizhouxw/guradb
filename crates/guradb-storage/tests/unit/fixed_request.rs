//! Independent literal CF1-A fixture; no sockets, clocks or authority stubs.
use crate::fixed_request::plan_fixed_request;
use guradb_common::cf1a::{decode, Contract, Integrity, ObjectRef, Payload};

// Copied from common's A golden binding, with three distinct member locations.
// Revision and envelope digests were calculated offline with Python hashlib,
// not with this planner or common's Rust encoder. No object bytes are fetched.
const BINDING: &str = r#"{
  "contract_version": "cf1a/1.0",
  "required_capabilities": [
    "fixed_read",
    "typed_json_v1",
    "strong_integrity",
    "catalog_cas"
  ],
  "payload": {
    "read_binding": {
      "resource": {
        "tenant_id": "tenant-1",
        "namespace_id": "namespace-1",
        "dataset_id": "dataset-1",
        "display_name": "图文\n知识库",
        "schema_id": "schema-1",
        "schema_version": 1,
        "schema_sha256": "fdd5e9cf283a8944c187e9cabc23f92368f3165755598102274595818138024d",
        "fields": [
          {
            "field_id": 1,
            "name": "id",
            "type": "text",
            "nullable": false,
            "role": "logical_id"
          },
          {
            "field_id": 2,
            "name": "version",
            "type": "text",
            "nullable": false,
            "role": "record_version"
          },
          {
            "field_id": 3,
            "name": "number",
            "type": "int8",
            "nullable": true,
            "role": "value"
          },
          {
            "field_id": 4,
            "name": "active",
            "type": "bool",
            "nullable": false,
            "role": "value"
          }
        ]
      },
      "revision": {
        "data_revision_id": "revision-1",
        "dataset_id": "dataset-1",
        "schema_id": "schema-1",
        "schema_version": 1,
        "parent_revision_ids": [],
        "sources": [
          {
            "source_id": "source-1",
            "source_version_id": "source-version-1",
            "format": "manifest",
            "format_version": "1",
            "snapshot_id": "snapshot-1",
            "source_schema_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "resource_schema_sha256": "fdd5e9cf283a8944c187e9cabc23f92368f3165755598102274595818138024d",
            "metadata": {
              "backend_id": "local_simulation",
              "bucket": "fixture",
              "key": "metadata.json",
              "version": "object-v1",
              "size_bytes": 8,
              "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "integrity": {
                "mode": "whole_sha256",
                "block_size": 0,
                "block_sha256": [],
                "proof_ref": ""
              }
            },
            "field_mapping": [
              {
                "source_field_id": 1,
                "resource_field_id": 1,
                "type": "text",
                "source_type": "text",
                "transform": "identity"
              },
              {
                "source_field_id": 2,
                "resource_field_id": 2,
                "type": "text",
                "source_type": "text",
                "transform": "identity"
              },
              {
                "source_field_id": 3,
                "resource_field_id": 3,
                "type": "int8",
                "source_type": "int8",
                "transform": "identity"
              },
              {
                "source_field_id": 4,
                "resource_field_id": 4,
                "type": "bool",
                "source_type": "bool",
                "transform": "identity"
              }
            ],
            "protected_until_unix_ms": 100000,
            "protection_ref": "source-protection-1"
          }
        ],
        "objects": [
          {
            "backend_id": "local_simulation",
            "bucket": "fixture",
            "key": "data.parquet",
            "version": "object-v1",
            "size_bytes": 8,
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "integrity": {
              "mode": "whole_sha256",
              "block_size": 0,
              "block_sha256": [],
              "proof_ref": ""
            }
          }
        ],
        "content_sha256": "fb5325699f9f8c0550d33adb45e75e3670d67bbae8908a6e2df5c8de4c2f4dbe"
      },
      "view": {
        "read_view_id": "view-1",
        "data_revision_id": "revision-1",
        "publication_generation": 2,
        "publication_sequence": 1,
        "required_artifact_ids": [
          "artifact-1"
        ],
        "index_requirements": [
          {
            "artifact_id": "artifact-1",
            "model_id": "synthetic-model",
            "model_version": "model-v1",
            "dimension": 3,
            "metric": "squared_l2",
            "analyzer": "none",
            "format_id": "fixture-exact-vector",
            "format_version": 1,
            "configuration_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "processing_version": "identity-v1"
          }
        ],
        "descriptor_sha256": "08ed36ff56f310edc9a350a52cbcc15d0c05773b1525207566f9e5353d9219be"
      },
      "indexes": [
        {
          "artifact_id": "artifact-1",
          "build_id": "build-1",
          "data_revision_id": "revision-1",
          "schema_sha256": "fdd5e9cf283a8944c187e9cabc23f92368f3165755598102274595818138024d",
          "kind": "exact_vector",
          "model_id": "synthetic-model",
          "model_version": "model-v1",
          "dimension": 3,
          "format_id": "fixture-exact-vector",
          "format_version": 1,
          "configuration_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "processing_version": "identity-v1",
          "metric": "squared_l2",
          "analyzer": "none",
          "source_version_ids": [
            "source-version-1"
          ],
          "logical_mapping_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "deletion_mode": "none",
          "deletion_watermark": 0,
          "shard_count": 1,
          "shards": [
            {
              "backend_id": "local_simulation",
              "bucket": "fixture",
              "key": "index.blocks",
              "version": "object-v1",
              "size_bytes": 10,
              "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "integrity": {
                "mode": "block_sha256",
                "block_size": 4,
                "block_sha256": [
                  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                  "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                ],
                "proof_ref": "registered-proof-1"
              }
            }
          ],
          "build_usage": {
            "object_requests": 1,
            "object_bytes": 8,
            "memory_bytes": 512,
            "output_bytes": 128,
            "elapsed_ms": 2
          },
          "reader_capabilities": [
            "fixed_read"
          ]
        }
      ],
      "context": {
        "request_id": "request-1",
        "query_id": "query-1",
        "tenant_id": "tenant-1",
        "dataset_id": "dataset-1",
        "schema_id": "schema-1",
        "schema_version": 1,
        "data_revision_id": "revision-1",
        "read_view_id": "view-1",
        "source_version_ids": [
          "source-version-1"
        ],
        "artifact_ids": [
          "artifact-1"
        ],
        "auth": {
          "tenant_id": "tenant-1",
          "subject_id": "subject-1",
          "dataset_id": "dataset-1",
          "actions": [
            "read"
          ],
          "policy_epoch": 1,
          "expires_unix_ms": 90000,
          "delegation_ref": "delegation-1"
        },
        "pin": {
          "pin_id": "pin-1",
          "lease_id": "lease-1",
          "data_revision_id": "revision-1",
          "read_view_id": "view-1",
          "expires_unix_ms": 100000
        },
        "bound_at_unix_ms": 1000,
        "deadline_unix_ms": 31000,
        "remaining_ttl_ms": 30000,
        "budget": {
          "memory_bytes": 4096,
          "object_requests": 8,
          "object_bytes": 4096,
          "candidates": 16,
          "top_k": 3,
          "graph_edges": 1,
          "output_bytes": 4096,
          "concurrency": 1,
          "temp_bytes": 4096
        },
        "cancellation_id": "cancel-1",
        "trace_id": "trace-1",
        "span_id": "span-1"
      }
    }
  }
}"#;
const BINDING_SHA256: &str = "17d40584d24b6834767fcd2eb1340a1d29ec4bf6a3b48984b4d32e15e829eb65";

fn binding() -> Contract {
    decode(BINDING.as_bytes()).unwrap()
}

fn references(binding: &Contract) -> [ObjectRef; 3] {
    let Payload::ReadBinding(value) = &binding.envelope().payload else {
        panic!("literal fixture must be a read binding");
    };
    [
        value.revision.sources[0].metadata.clone(),
        value.revision.objects[0].clone(),
        value.indexes[0].shards[0].clone(),
    ]
}

fn rejected(binding: &Contract, reference: &ObjectRef, offset: u64, length: u64, code: &str) {
    assert_eq!(
        plan_fixed_request(binding, reference, offset, length)
            .unwrap_err()
            .code,
        code
    );
}

#[test]
fn plans_all_three_member_origins_and_aligned_short_tail() {
    let binding = binding();
    assert_eq!(binding.sha256(), BINDING_SHA256);
    let refs = references(&binding);
    for (index, key, length) in [
        (0, "metadata.json", 8),
        (1, "data.parquet", 8),
        (2, "index.blocks", 10),
    ] {
        let plan = plan_fixed_request(&binding, &refs[index], 0, length).unwrap();
        assert_eq!(plan.binding_sha256(), BINDING_SHA256);
        assert_eq!(plan.reference().key, key);
        assert_eq!(plan.reference().version, "object-v1");
        assert_eq!((plan.offset(), plan.length()), (0, length));
    }
    for (offset, length) in [(0, 4), (4, 4), (8, 2), (4, 6)] {
        let plan = plan_fixed_request(&binding, &refs[2], offset, length).unwrap();
        assert_eq!((plan.offset(), plan.length()), (offset, length));
    }
}

#[test]
fn null_latest_empty_and_malformed_typed_references_fail_closed() {
    let binding = binding();
    let base = references(&binding)[0].clone();
    for (version, code) in [
        ("", "invalid_contract"),
        ("null", "unsupported_capability"),
        ("latest", "unsupported_capability"),
        ("object-v2", "unauthorized"),
    ] {
        let mut reference = base.clone();
        reference.version = version.into();
        rejected(&binding, &reference, 0, 8, code);
    }
    let edits: [fn(&mut ObjectRef); 5] = [
        |r| r.key.clear(),
        |r| r.sha256 = "not-a-sha256".into(),
        |r| r.size_bytes = 0,
        |r| r.integrity.mode = "unknown".into(),
        |r| r.integrity.proof_ref = "unclaimed-whole-proof".into(),
    ];
    for edit in edits {
        let mut reference = base.clone();
        edit(&mut reference);
        rejected(&binding, &reference, 0, 8, "invalid_contract");
    }
}

#[test]
fn whole_and_block_ranges_reject_zero_overrun_overflow_and_partial_blocks() {
    let binding = binding();
    let refs = references(&binding);
    for (offset, length) in [
        (0, 0),
        (8, 1),
        (9, 1),
        (0, 9),
        (1, 7),
        (0, u64::MAX),
        (u64::MAX, 1),
        (u64::MAX, u64::MAX),
    ] {
        rejected(&binding, &refs[0], offset, length, "invalid_contract");
    }
    for (offset, length) in [(1, 4), (0, 3), (4, 5), (8, 3), (10, 1)] {
        rejected(&binding, &refs[2], offset, length, "invalid_contract");
    }
    for width in [0, 3, u64::MAX] {
        let mut reference = refs[2].clone();
        reference.integrity.block_size = width;
        rejected(&binding, &reference, 0, 10, "invalid_contract");
    }
    let mut reference = refs[2].clone();
    reference.integrity.block_sha256.pop();
    rejected(&binding, &reference, 0, 10, "invalid_contract");
    reference = refs[2].clone();
    reference.integrity.block_sha256[0] = "BAD".into();
    rejected(&binding, &reference, 0, 10, "invalid_contract");
}

#[test]
fn membership_checks_every_identity_size_digest_and_integrity_field() {
    let binding = binding();
    let refs = references(&binding);
    let edits: [fn(&mut ObjectRef); 8] = [
        |r| r.backend_id = "different_backend".into(),
        |r| r.bucket = "other-bucket".into(),
        |r| r.key = "unlisted-object".into(),
        |r| r.version = "different-version".into(),
        |r| r.size_bytes = 12,
        |r| r.sha256 = "b".repeat(64),
        |r| r.integrity.block_sha256[0] = "d".repeat(64),
        |r| r.integrity.proof_ref = "self-declared-proof".into(),
    ];
    for edit in edits {
        let mut reference = refs[2].clone();
        edit(&mut reference);
        // size 12 still needs three width-4 blocks, so shape remains valid.
        rejected(
            &binding,
            &reference,
            0,
            reference.size_bytes,
            "unauthorized",
        );
    }
    let mut reference = refs[2].clone();
    reference.integrity.block_size = 5;
    reference.integrity.block_sha256.pop();
    rejected(&binding, &reference, 0, 10, "unauthorized");
    reference.integrity = Integrity {
        mode: "whole_sha256".into(),
        block_size: 0,
        block_sha256: vec![],
        proof_ref: String::new(),
    };
    rejected(&binding, &reference, 0, 10, "unauthorized");
}

#[test]
fn owned_plan_retains_original_binding_and_reference_after_caller_changes() {
    let binding = binding();
    let mut reference = references(&binding)[2].clone();
    let plan = plan_fixed_request(&binding, &reference, 8, 2).unwrap();
    reference.version = "caller-rewrite".into();
    reference.integrity.block_sha256.clear();
    drop(binding);
    assert_eq!(plan.binding_sha256(), BINDING_SHA256);
    assert_eq!(plan.reference().version, "object-v1");
    assert_eq!(plan.reference().integrity.block_sha256.len(), 3);
    assert_eq!((plan.offset(), plan.length()), (8, 2));
    let mut detached = plan.reference().clone();
    detached.key.clear();
    assert_eq!(plan.reference().key, "index.blocks");
}

#[test]
fn common_ingress_rejects_unknown_versions_capabilities_and_missing_versions() {
    for (needle, replacement, code) in [
        ("cf1a/1.0", "cf1a/unknown", "unsupported_version"),
        (
            "strong_integrity",
            "unknown_capability",
            "unsupported_capability",
        ),
        ("\"version\": \"object-v1\",", "", "invalid_contract"),
        (
            "\"version\": \"object-v1\"",
            "\"version\": null",
            "invalid_contract",
        ),
    ] {
        let raw = BINDING.replace(needle, replacement);
        assert_eq!(decode(raw.as_bytes()).unwrap_err().code, code);
    }
    // Renaming a binding does not produce valid descriptors: its extra context
    // is rejected by common before any plan can be formed.
    let raw = BINDING.replace("read_binding", "read_descriptors");
    assert_eq!(decode(raw.as_bytes()).unwrap_err().code, "invalid_contract");
}

#[test]
fn valid_nonbinding_contract_is_rejected_before_reference_validation() {
    let config = decode(
        br#"{
        "contract_version":"cf1a/1.0",
        "required_capabilities":["fixed_read","typed_json_v1","strong_integrity"],
        "payload":{"reader_config":{
            "max_envelope_bytes":1048576,"max_batch_rows":1024,"max_ttl_ms":30000,
            "capabilities":["fixed_read","typed_json_v1","strong_integrity","catalog_cas"]
        }}
    }"#,
    )
    .unwrap();
    let mut reference = references(&binding())[0].clone();
    reference.version = "null".into();
    rejected(&config, &reference, 0, 8, "invalid_contract");
}
