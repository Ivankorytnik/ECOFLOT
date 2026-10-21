// LEGACY-ONLY wrapper; DO NOT install it in an existing ECOFLOT server v5.1.
// For v5.1 see SYNC_ECOFLOT_2026-10-21.md: preserve the original
// findDuplicate_ function, site-form exception and ef5Procurement_ checks.
// Replace the OLD findDuplicate_ definition with this ONE definition.
// Add ecoflot_server_guards.gs as a separate file in the SAME project.
function findDuplicate_(sheet, headers, lead) {
  return ecoflotFindDuplicateV3_(sheet, headers, lead);
}
