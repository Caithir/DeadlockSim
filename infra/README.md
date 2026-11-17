# DeadlockSim — Azure Infrastructure

ARM templates and deploy scripts for running DeadlockSim on Azure App Service (Linux).

The app is a single static Rust binary (`deadlock-sim`) plus the `data/` directory. The deploy scripts
and the GitHub workflow build the binary, zip it with `data/` and `startup.sh`, and run it through the
app's startup command, so the built-in runtime stack only provides the Linux container. A `Dockerfile`
at the repository root is available for container-based hosting instead.

## Current Deployment

| Property | Value |
|---|---|
| **App Name** | `deadlocksim` |
| **URL** | https://deadlocksim.azurewebsites.net |
| **Resource Group** | `deadlocksim-rg` |
| **Region** | `westus3` |
| **SKU** | `Premium0V3` |
| **Runtime** | Static `deadlock-sim` binary on the built-in `PYTHON\|3.14` Linux image |
| **App Service Plan** | `ASP-deadlocksimrg-8ec5` |

## Quick Start — Deploy Code

The web app already exists. To push code changes:

```powershell
# PowerShell
.\infra\deploy-code.ps1
```

```bash
# Bash
./infra/deploy-code.sh
```

This builds a static release binary, configures the startup command and app settings, and zip-deploys the package.
It needs Rust with the `x86_64-unknown-linux-musl` target and `musl-tools`.

### View Logs

```bash
az webapp log tail --resource-group deadlocksim-rg --name deadlocksim
```

## Infrastructure (ARM Template)

The ARM template can provision supporting resources (VNet, App Insights, Log Analytics) alongside the web app. It supports referencing an existing App Service Plan via `existingAppServicePlanId`.

### Resources Created

| Resource | Purpose |
|---|---|
| **Virtual Network** | Isolated network with two subnets |
| **NSGs** (×2) | Network security groups for app and private endpoint subnets |
| **App Service Plan** | Linux plan (skipped if `existingAppServicePlanId` is set) |
| **Web App** | Linux app with VNet integration, managed identity, HTTPS-only |
| **Application Insights** | APM and telemetry |
| **Log Analytics Workspace** | Centralized logging for diagnostics |
| **Diagnostic Settings** | HTTP, console, app, and platform logs streamed to Log Analytics |
| **Private Endpoint** *(optional)* | Restricts web app to VNet-only access |
| **Private DNS Zone** *(optional)* | DNS resolution for private endpoint |

### Deploy Infrastructure

```bash
# Login
az login
az account set --subscription cc05efe5-7259-4c47-af9f-904b5a42fc8a

# Deploy (bash)
./infra/deploy.sh deadlocksim-rg westus3

# Deploy (PowerShell)
.\infra\deploy.ps1 -ResourceGroup deadlocksim-rg -Location westus3
```

## Parameters

Edit `azuredeploy.parameters.json` before deploying:

| Parameter | Default | Description |
|---|---|---|
| `appName` | `deadlocksim` | Globally unique web app name |
| `location` | Resource group location | Azure region |
| `skuName` | `P0v3` | App Service Plan tier |
| `runtimeStack` | `PYTHON\|3.14` | Built-in Linux image that hosts the binary (any stack works) |
| `existingAppServicePlanId` | *(empty)* | Existing plan resource ID (skips plan creation) |
| `vnetAddressPrefix` | `10.0.0.0/16` | VNet CIDR |
| `appSubnetPrefix` | `10.0.1.0/24` | App integration subnet |
| `privateEndpointSubnetPrefix` | `10.0.2.0/24` | Private endpoint subnet |
| `enablePrivateEndpoint` | `false` | Lock down to VNet-only |
| `logRetentionDays` | `30` | Log Analytics retention |

## How It Works

1. The deployment package holds the static `deadlock-sim` binary, `data/` and `startup.sh`. Oryx builds are
   disabled (`SCM_DO_BUILD_DURING_DEPLOYMENT=false`) because nothing needs installing.
2. The startup command `bash startup.sh` runs `deadlock-sim serve --host 0.0.0.0` on `PORT`
   (falling back to `WEBSITES_PORT`, then 8080).
3. The UI is plain HTTP + JSON; WebSockets are no longer needed (the setting is harmless if left on).
4. `GET /healthz` returns `ok` and can be used as the App Service health check path.

## Security Notes

- **No secrets in templates** — App Insights connection string is resolved at deploy time via ARM reference.
- **Managed Identity** enabled — use for Azure SDK auth instead of keys.
- **HTTPS-only**, FTPS disabled, TLS 1.2 minimum.
- Set `enablePrivateEndpoint=true` to remove public internet access.
