{{- define "cap.name" -}}
{{- $root := .root -}}
{{- if eq $root.Values.naming.mode "legacy" -}}
{{- if eq .component "db-config" -}}database-config
{{- else if eq .component "db-secret" -}}database-secret
{{- else -}}{{ .component }}{{- end -}}
{{- else -}}
{{- $release := $root.Release.Name -}}
{{- if gt (len $release) 35 -}}
{{- $release = printf "%s-%s" ($release | trunc 26 | trimSuffix "-") ($release | sha256sum | trunc 8) -}}
{{- end -}}
{{- printf "%s-cap-%s" $release .component -}}
{{- end -}}
{{- end -}}

{{- define "cap.selector" -}}
{{- if eq .root.Values.naming.mode "legacy" -}}
app: {{ .component }}
{{- else -}}
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}
{{- end -}}

{{- define "cap.labels" -}}
app.kubernetes.io/name: cap
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "cap.job" -}}
{{ include "cap.name" (dict "root" . "component" "migrate") }}-{{ .Release.Revision }}
{{- end -}}

{{- define "cap.identity" -}}
{{- dict "mode" .Values.naming.mode "database" .Values.database.name "user" .Values.database.user "storageClass" .Values.database.persistence.storageClass "size" .Values.database.persistence.size | toJson -}}
{{- end -}}
