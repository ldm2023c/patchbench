# Deployconf

A local deployment-plan inspector. Run `python -m deployconf.cli --help`.
No network requests are made. Python 3.12+, standard library only.

Settings resolve independently: explicit CLI > present DEPLOY_* environment
variable > [deploy] TOML setting > built-in default. Omitted CLI options must
not override lower sources. Zero retries and an empty label are valid explicit
values; an empty endpoint is invalid. Validate the selected effective values.
Unknown TOML deployment keys are rejected. Errors produce exit code 2.

Run the complete suite with `python -B -m unittest -v`.
