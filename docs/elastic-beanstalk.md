# Deploy OpenCaliber to Elastic Beanstalk

Deploy the authenticated Python service using the included ASGI entry point, runtime configuration, retained-storage setup and source-bundle builder.

## Deployment shape

- Python on Amazon Linux 2023; use a current supported Python 3.12+ platform release supporting environment secrets (released March 26, 2025 or later).
- Uvicorn `application:application`, port 8000, exactly one worker and one app instance. Do not use Gunicorn's default WSGI worker for this ASGI app.
- Public home page, walkthrough, Agents Library, 64 starter ZIPs and the desktop console download.
- `/console` and evaluation APIs require HTTPS and shared-workspace authentication. Browser username is `admin`; password is the generated access token. API clients may use `Authorization: Bearer TOKEN`. Never include tokens in URLs.
- This is one shared workspace, not user accounts or tenant isolation. Every authenticated operator can see the same runs and change settings. The existing downloaded desktop SDK remains loopback-only; use a separate authenticated HTTPS client for the hosted API.
- The template provisions an HTTPS Application Load Balancer with an existing ACM certificate. HTTP listener is disabled. One instance subnet pins the data volume's AZ; the ALB needs two subnets in distinct AZs. The instance subnet must have outbound connectivity to download Python dependencies and reach AWS APIs.
- A retained encrypted 10 GiB gp3 EBS volume mounts at `/mnt/opencaliber`; SQLite is at `/mnt/opencaliber/data/agent-console.sqlite3`. Source releases never include existing evaluation history. Public downloads never include server credentials.
- Health probes `/health/live` and `/health/ready` need no authentication and expose no customer data. Readiness checks SQLite. TLS terminates at the ALB; Uvicorn trusts proxy headers only from nginx on loopback. Preserve the original Host and HTTPS protocol headers through your proxy chain.

## Build and validate (no AWS access)

```powershell
python -m pip install -r requirements.txt
python -m pip install httpx PyYAML
python deploy/build_bundle.py
python tools/check_deployment.py
python -m unittest tests.test_cloud_deployment -v
```

Source bundle: `dist/opencaliber-elasticbeanstalk.zip`. `application.py`, `Procfile`, and `requirements.txt` are at ZIP root, not under a parent directory. The bundle contains the site/video, evaluator, library downloads, desktop-download source dependencies and deployment configuration. It excludes artifacts, SQLite databases, `.env` files, AWS credentials, model weights, training code, development tests and the sibling repository. Generated agent ZIPs contain only synthetic examples, `.env.example`, code, configuration and their own runnable tests.

`requirements.txt` now contains only the hosted runtime dependencies. The earlier classifier dependencies are preserved in `requirements-training.txt`; Colab uses `requirements-colab.txt`. Downloaded console/agent packs still use Python's standard library.

## AWS configuration

Use your normal AWS profile or instance role. Do not place credentials in the source tree. The optional helper requires an existing private artifact bucket in the selected region, a supported Python AL2023 platform ARN, VPC/subnets, and an ACM certificate in that region covering the public hostname.

```powershell
python deploy/aws_deploy.py --region ap-south-1 --stack opencaliber --bucket YOUR_PRIVATE_RELEASE_BUCKET --platform-arn "YOUR_PYTHON_AL2023_PLATFORM_ARN" --vpc-id vpc-REPLACE --subnet-id subnet-INSTANCE --az ap-south-1a --alb-subnets subnet-ALB1,subnet-ALB2 --certificate-arn "YOUR_ACM_CERTIFICATE_ARN" --public-origin https://opencaliber.example.com
```

Without `--apply`, this command builds the ZIP and writes `dist/deployment-plan.json`; it makes no AWS calls. Review the plan and template. Adding `--apply` uploads the source and submits a CloudFormation create/update with IAM capabilities; that provisions billable resources. This work does not run that action.

The template creates the EB application/version/environment, instance and service roles, encrypted data volume, and a retained Secrets Manager token. It does not create a domain, hosted zone, DNS alias, ACM certificate, release bucket, backups, WAF, or SSO. Point the configured public hostname to the environment/ALB using your DNS configuration, and verify certificate and HTTPS behavior before using the workspace. The public origin must match the request Host exactly.

After provisioning, get the token through your authorized Secrets Manager console/CLI workflow; do not print it in deployment logs or commit it. Rotation requires refreshing EB environment secrets and restarting the app. Never reuse a sibling application's credentials.

## Console-upload alternative

Upload the source ZIP to a Python EB environment and configure these properties before the app starts:

| Name | Value |
|---|---|
| `OPENCALIBER_PUBLIC_ORIGIN` | Your bare HTTPS origin, without a trailing slash or path |
| `OPENCALIBER_ADMIN_TOKEN` | A random secret of at least 32 characters, supplied as an environment secret |
| `OPENCALIBER_DATA_DIR` | `/mnt/opencaliber/data` |
| `OPENCALIBER_STORAGE_MODE` | `retained` |
| `OPENCALIBER_DATA_VOLUME_ID` | The dedicated EBS volume ID, in the instance AZ |
| `PORT` | `8000` |

The instance role needs `secretsmanager:GetSecretValue` on that secret, volume describe/attach/tag access for its dedicated volume, release-bucket read access and log permissions. For first initialization only, an empty unpartitioned volume must have `OpenCaliberStorageState=fresh`. Bootstrap refuses to format existing unmanaged filesystems or force-detach a live volume. It marks initialized storage and checks that the mounted filesystem UUID matches the selected volume.

`OPENCALIBER_STORAGE_MODE=instance` is an explicit disposable staging option. It creates the same directory on the instance disk; history is lost on replacement. Retained mode never silently falls back. No AWS/provider credentials or OpenAI/Anthropic models are needed by the evaluator itself.

## Operations and limits

SQLite and the retained volume require single-instance operation and one worker. No blue/green or rolling deployment that attaches the same volume to concurrent instances is supported. AllAtOnce source updates may cause downtime. An instance replacement can wait for the old volume attachment to release; if necessary, schedule a maintenance window, stop the old application/instance and verify clean volume release before retrying. Never force detach a live database.

Retain is not a backup. Configure encrypted EBS snapshots and test restoration separately. Plan retained-volume/secret cleanup when deleting the stack, because they remain billable. Before migrating existing data, take a consistent SQLite backup while writes are paused; do not copy a live `.sqlite3` file blindly.

Hosted evaluations default to redacted evidence, unlike manual evaluations in the desktop runtime. Redacted runs cannot be replayed from saved inputs. Operators may explicitly choose raw storage. Identity/permissions supplied by clients are not authenticated agent identities. Basic/Bearer protects access to the shared workspace but does not provide per-user RBAC, audit identity or tenant isolation. Do not use this as a multi-company SaaS deployment.

## Verification after provisioning

Check public home/library and a ZIP download; `/health/ready` should return 200. Confirm unauthenticated HTTPS `/api/state` returns 401, HTTP workspace requests refuse credentials, wrong Host/Origin returns 403, and authenticated sample evaluation saves a redacted run. Play and seek the walkthrough. Re-deploy the same source and verify saved history remains. Instance replacement and volume restore require an actual AWS rehearsal; offline tests do not establish those outcomes.

References: [AWS Python Procfile](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/python-configuration-procfile.html), [environment secrets](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/AWSHowTo.secrets.env-vars.html), [platform hooks](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/platforms-linux-extend.hooks.html).
