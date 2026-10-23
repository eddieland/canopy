-- sha256 of 0081_run_model.sql: 66979886f79043c93a6b6a3a95bc5f6b89bd0ba257bf45a1c117a3ca5d11f7a7

UPDATE runs SET model = 'acme/fake-model' WHERE id = (SELECT min(id) FROM runs);
