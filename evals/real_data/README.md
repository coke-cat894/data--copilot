# Real Dataset Manual Evaluation Protocol

Use at least one unfamiliar external dataset in addition to the controlled
`orders_demo.csv` fixture. Keep the file outside the repository when its
license, copyright, sensitivity, or size makes committing inappropriate.

For each dataset record:

- dataset name, authoritative source URL, format, approximate size, and columns;
- whether the data file was committed (normally no);
- at least five questions covering overview, profile/distribution,
  aggregate/trend, filtered records, and quality or insufficient evidence;
- for each question: Tools used, answer, correct, grounded, useful, and problems;
- provider/model and date, without API keys; and
- observed failure modes rather than silently repairing or hiding them.

The manual protocol must use the normal `data-copilot <dataset-path>` CLI or
the same Agent boundary. Do not copy expected-answer notes into Agent context.
