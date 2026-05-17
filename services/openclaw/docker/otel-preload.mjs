import { createRequire } from "module";
const require = createRequire(import.meta.url);

const { NodeSDK } = require("@opentelemetry/sdk-node");
const { getNodeAutoInstrumentations } = require("@opentelemetry/auto-instrumentations-node");
const { OTLPTraceExporter } = require("@opentelemetry/exporter-trace-otlp-proto");
const { resourceFromAttributes } = require("@opentelemetry/resources");
const { ATTR_SERVICE_NAME } = require("@opentelemetry/semantic-conventions");
const {
  CompositePropagator,
  W3CBaggagePropagator,
  W3CTraceContextPropagator,
} = require("@opentelemetry/core");
const { diag, DiagConsoleLogger, DiagLogLevel } = require("@opentelemetry/api");

diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.DEBUG);


const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME || "openclaw-gateway",
  }),
  textMapPropagator: new CompositePropagator({
    propagators: [new W3CTraceContextPropagator(), new W3CBaggagePropagator()],
  }),
  instrumentations: [getNodeAutoInstrumentations()],
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT 
      ? (process.env.OTEL_EXPORTER_OTLP_ENDPOINT.endsWith("/v1/traces") 
          ? process.env.OTEL_EXPORTER_OTLP_ENDPOINT 
          : `${process.env.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces`)
      : "http://otel-collector:4318/v1/traces",
  }),
});

sdk.start();
process.env.OPENCLAW_OTEL_PRELOADED = "1";

const shutdown = () => {
  sdk.shutdown()
    .then(() => console.log("OTel SDK shut down"))
    .catch((err) => console.log("Error shutting down OTel SDK", err))
    .finally(() => process.exit(0));
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
