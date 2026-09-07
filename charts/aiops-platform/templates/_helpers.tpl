{{/*
Names and labels, in the style of charts/ollama.
*/}}
{{- define "aiops-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aiops-platform.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "aiops-platform.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "aiops-platform.labels" -}}
helm.sh/chart: {{ include "aiops-platform.chart" . }}
app.kubernetes.io/name: {{ include "aiops-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for one component: include "aiops-platform.componentLabels" (dict "root" $ "component" "backend")
*/}}
{{- define "aiops-platform.componentLabels" -}}
app.kubernetes.io/name: {{ include "aiops-platform.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
The common labels (aiops-platform.labels) plus app.kubernetes.io/component,
for a resource's metadata.labels: include "aiops-platform.labelsForComponent" (dict "root" $ "component" "backend")
*/}}
{{- define "aiops-platform.labelsForComponent" -}}
{{ include "aiops-platform.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
A host under the parent domain: include "aiops-platform.host" (dict "root" $ "label" "ui")
*/}}
{{- define "aiops-platform.host" -}}
{{ .label }}.{{ .root.Values.global.parentDomain }}
{{- end }}

{{- define "aiops-platform.gatewayName" -}}
{{- if .Values.gateway.create }}{{ include "aiops-platform.fullname" . }}{{ else }}{{ .Values.gateway.name }}{{ end }}
{{- end }}

{{- define "aiops-platform.gatewayNamespace" -}}
{{- if .Values.gateway.create }}{{ .Release.Namespace }}{{ else }}{{ .Values.gateway.namespace }}{{ end }}
{{- end }}

{{/*
The realm issuer: the bundled Keycloak behind the auth host, or the external one.
*/}}
{{- define "aiops-platform.issuer" -}}
{{- if .Values.keycloak.enabled -}}
https://{{ include "aiops-platform.host" (dict "root" . "label" .Values.gateway.hosts.auth) }}/realms/aiops
{{- else -}}
{{ required "keycloak.external.issuer is required when keycloak.enabled is false" .Values.keycloak.external.issuer | trimSuffix "/" }}
{{- end -}}
{{- end }}

{{/*
The Secret for one bundled-or-external dependency (the platform Secret
unless the dependency is external and names its own):
include "aiops-platform.dependencySecret" (dict "root" $ "key" "keycloak")
*/}}
{{- define "aiops-platform.dependencySecret" -}}
{{- $dep := index .root.Values .key -}}
{{- if and (not $dep.enabled) $dep.external.existingSecret }}{{ $dep.external.existingSecret }}{{ else }}{{ .root.Values.secrets.name }}{{ end }}
{{- end }}

{{/* The Secret holding KEYCLOAK_CLIENT_SECRET. */}}
{{- define "aiops-platform.keycloakSecret" -}}
{{- include "aiops-platform.dependencySecret" (dict "root" . "key" "keycloak") }}
{{- end }}

{{- define "aiops-platform.databaseHost" -}}
{{- if .Values.postgresql.enabled }}{{ .Values.postgresql.fullnameOverride }}{{ else }}{{ required "postgresql.external.host is required when postgresql.enabled is false" .Values.postgresql.external.host }}{{ end }}
{{- end }}

{{/* What backend/db/database.py parses: scheme, host and port only. */}}
{{- define "aiops-platform.databaseUrl" -}}
postgresql://{{ include "aiops-platform.databaseHost" . }}:{{ if .Values.postgresql.enabled }}5432{{ else }}{{ .Values.postgresql.external.port }}{{ end }}
{{- end }}

{{- define "aiops-platform.databaseName" -}}
{{- if .Values.postgresql.enabled }}{{ .Values.postgresql.auth.database }}{{ else }}{{ .Values.postgresql.external.database }}{{ end }}
{{- end }}

{{- define "aiops-platform.databaseUser" -}}
{{- if .Values.postgresql.enabled }}postgres{{ else }}{{ .Values.postgresql.external.username }}{{ end }}
{{- end }}

{{/* The Secret holding DATABASE_PASSWORD. */}}
{{- define "aiops-platform.databaseSecret" -}}
{{- include "aiops-platform.dependencySecret" (dict "root" . "key" "postgresql") }}
{{- end }}

{{- define "aiops-platform.litellmUrl" -}}
{{- if .Values.litellm.enabled }}http://{{ .Values.litellm.fullnameOverride }}:4000{{ else }}{{ .Values.litellm.external.url | trimSuffix "/" }}{{ end }}
{{- end }}

{{/* The Secret holding LITELLM_MASTER_KEY. */}}
{{- define "aiops-platform.litellmSecret" -}}
{{- include "aiops-platform.dependencySecret" (dict "root" . "key" "litellm") }}
{{- end }}

{{- define "aiops-platform.backendFullname" -}}
{{ include "aiops-platform.fullname" . }}-backend
{{- end }}

{{- define "aiops-platform.frontendFullname" -}}
{{ include "aiops-platform.fullname" . }}-frontend
{{- end }}

{{- define "aiops-platform.backendImage" -}}
{{ .Values.backend.image.repository }}:{{ .Values.backend.image.tag | default .Values.global.imageTag }}
{{- end }}

{{- define "aiops-platform.frontendImage" -}}
{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Values.global.imageTag }}
{{- end }}

{{- define "aiops-platform.backendServiceAccountName" -}}
{{- if .Values.backend.serviceAccount.create }}
{{- default (printf "%s-backend" (include "aiops-platform.fullname" .)) .Values.backend.serviceAccount.name }}
{{- else }}
{{- required "backend.serviceAccount.name is required when backend.serviceAccount.create is false" .Values.backend.serviceAccount.name }}
{{- end }}
{{- end }}
