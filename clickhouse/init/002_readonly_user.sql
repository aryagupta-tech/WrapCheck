CREATE USER IF NOT EXISTS wrapcheck_mcp IDENTIFIED WITH plaintext_password BY 'wrapcheck-mcp-local';
GRANT SELECT ON wrapcheck.* TO wrapcheck_mcp;
