-- Run as a DBA in the same PDB after the spike. CASCADE also drops any
-- DBTOOLS$MCP_LOG table SQLcl may have created in the spike_ro schema.
DROP USER spike_ro CASCADE;
