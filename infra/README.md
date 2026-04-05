# DeadlockSim — Azure Infrastructure

ARM templates and deploy scripts for running DeadlockSim on Azure App Service (Linux/Python).

## Current Deployment

| Property | Value |
|---|---|
| **App Name** | `deadlocksim` |
| **URL** | https://deadlocksim.azurewebsites.net |
| **Resource Group** | `deadlocksim-rg` |
| **Region** | `westus3` |
| **SKU** | `Premium0V3` |
| **Runtime** | `PYTHON\|3.14` |
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

This configures the startup command, app settings, WebSockets, and deploys the code via `az webapp up`.

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
| **Web App** | Python Linux app with VNet integration, managed identity, HTTPS-only |
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
| `pythonVersion` | `3.14` | Python runtime |
| `existingAppServicePlanId` | *(empty)* | Existing plan resource ID (skips plan creation) |
| `vnetAddressPrefix` | `10.0.0.0/16` | VNet CIDR |
| `appSubnetPrefix` | `10.0.1.0/24` | App integration subnet |
| `privateEndpointSubnetPrefix` | `10.0.2.0/24` | Private endpoint subnet |
| `enablePrivateEndpoint` | `false` | Lock down to VNet-only |
| `logRetentionDays` | `30` | Log Analytics retention |

## How It Works

1. **startup.sh** (project root) — installs the package (`pip install -e .`) and runs `deadlock-sim-gui`
2. **NiceGUI** binds to `0.0.0.0:8080`; Azure's `WEBSITES_PORT=8080` routes traffic
3. **WebSockets** must be enabled — NiceGUI uses them for real-time UI updates

## Security Notes

- **No secrets in templates** — App Insights connection string is resolved at deploy time via ARM reference.
- **Managed Identity** enabled — use for Azure SDK auth instead of keys.
- **HTTPS-only**, FTPS disabled, TLS 1.2 minimum.
- **WebSockets enabled** — required by NiceGUI's real-time UI.
- Set `enablePrivateEndpoint=true` to remove public internet access.
