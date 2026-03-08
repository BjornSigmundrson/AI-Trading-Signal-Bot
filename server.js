const express = require("express");
const fs = require("fs");
const https = require("https");
require("dotenv").config();

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 4021;
const payTo = process.env.RECEIVING_WALLET;
const price = process.env.SIGNAL_PRICE || "0.50";
const network = process.env.NETWORK_ID || "base-mainnet";
const PUBLIC_URL = process.env.PUBLIC_URL || "http://localhost:" + PORT;

if (!payTo) {
    console.log("ОШИБКА: RECEIVING_WALLET не задан в .env");
    process.exit(1);
}

function verifyPayment(paymentHeader, callback) {
    if (!paymentHeader) return callback(false);
    var body = JSON.stringify({
        payment: paymentHeader,
        paymentRequirements: {
            scheme: "exact",
            network: network,
            maxAmountRequired: (parseFloat(price) * 1000000).toString(),
            resource: PUBLIC_URL + "/signal",
            description: "AI Trading Signal",
            mimeType: "application/json",
            payTo: payTo,
            maxTimeoutSeconds: 300,
            asset: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            outputSchema: null,
            extra: { name: "USDC", version: "2" }
        }
    });
    var options = {
        hostname: "x402.org",
        path: "/facilitator/verify",
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(body)
        }
    };
    var req = https.request(options, function(res) {
        var data = "";
        res.on("data", function(chunk) { data += chunk; });
        res.on("end", function() {
            try { callback(JSON.parse(data).isValid === true); }
            catch(e) { callback(false); }
        });
    });
    req.on("error", function() { callback(false); });
    req.write(body);
    req.end();
}

app.get("/", function(req, res) {
    res.json({
        name: "AI Trading Signal Service",
        protocol: "x402",
        price_per_signal: "$" + price + " USDC",
        network: network,
        wallet: payTo,
        endpoints: { paid: "GET /signal", free: "GET /status" }
    });
});

app.get("/status", function(req, res) {
    try {
        var data = JSON.parse(fs.readFileSync("last_signal.json", "utf8"));
        res.json({ status: "running", symbol: data.symbol, price: data.price, action: data.action, updated: data.timestamp });
    } catch(e) {
        res.json({ status: "pending", message: "Запусти agent.py сначала" });
    }
});

app.get("/signal", function(req, res) {
    var paymentHeader = req.headers["x-payment"] || req.headers["payment"];
    if (!paymentHeader) {
        res.status(402).json({
            x402Version: 1,
            error: "Payment required",
            accepts: [{
                scheme: "exact",
                network: network,
                maxAmountRequired: (parseFloat(price) * 1000000).toString(),
                resource: PUBLIC_URL + "/signal",
                description: "AI Trading Signal - RSI + MACD + Claude Analysis",
                mimeType: "application/json",
                payTo: payTo,
                maxTimeoutSeconds: 300,
                asset: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                extra: { name: "USDC", version: "2" }
            }]
        });
        return;
    }
    verifyPayment(paymentHeader, function(isValid) {
        if (!isValid) { res.status(402).json({ error: "Payment invalid" }); return; }
        try {
            var signal = JSON.parse(fs.readFileSync("last_signal.json", "utf8"));
            res.json({ status: "success", paid: "$" + price + " USDC", signal: signal });
        } catch(e) {
            res.status(503).json({ error: "Signal not ready" });
        }
    });
});

app.listen(PORT, function() {
    console.log("==================================================");
    console.log("x402 Сервер запущен!");
    console.log("URL: " + PUBLIC_URL);
    console.log("Цена: $" + price + " USDC");
    console.log("Кошелёк: " + payTo);
    console.log("==================================================");
});