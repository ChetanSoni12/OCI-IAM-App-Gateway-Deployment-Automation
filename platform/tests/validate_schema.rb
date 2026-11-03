#!/usr/bin/env ruby
# frozen_string_literal: true

require "psych"
require "yaml"

def assert_unique_mapping_keys(node, path = [])
  case node
  when Psych::Nodes::Mapping
    seen = {}
    node.children.each_slice(2) do |key_node, value_node|
      key = key_node.is_a?(Psych::Nodes::Scalar) ? key_node.value : key_node.to_s
      raise "duplicate YAML key at #{(path + [key]).join('.')}: #{key}" if seen[key]

      seen[key] = true
      assert_unique_mapping_keys(value_node, path + [key])
    end
  when Psych::Nodes::Sequence
    node.children.each_with_index { |child, index| assert_unique_mapping_keys(child, path + [index.to_s]) }
  end
end

schema_path = File.expand_path("../schema.yaml", __dir__)
document = Psych.parse_file(schema_path)
assert_unique_mapping_keys(document.root)
schema = YAML.safe_load(File.read(schema_path), aliases: false)

required_variables = %w[
  region
  compartment_ocid
  tenancy_ocid
  release_identity_domain_url
  release_client_id
  release_client_secret
  ocir_pull_username
  ocir_pull_auth_token
  vault_mode
]
missing = required_variables.reject { |name| schema.fetch("variables").key?(name) }
raise "schema is missing required platform inputs: #{missing.join(', ')}" unless missing.empty?

raise "release_client_secret must be a password field" unless schema.dig("variables", "release_client_secret", "type") == "password"
raise "existing_vault_id must use an OCI Vault picker" unless schema.dig("variables", "existing_vault_id", "type") == "oci:kms:vault:id"

puts "Platform schema passed duplicate-key and input checks"
