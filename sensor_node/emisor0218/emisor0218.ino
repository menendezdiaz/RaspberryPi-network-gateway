#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>


// Configuracion de pines
static const int E32_RX_PIN = 16;
static const int E32_TX_PIN = 17;
static const int PIN_M0 = 25;
static const int PIN_M1 = 26;

HardwareSerial LORA(2);
Adafruit_AHTX0 aht;




void setup() {
  Serial.begin(115200);

  pinMode(PIN_M0, OUTPUT);
  pinMode(PIN_M1, OUTPUT);
  digitalWrite(PIN_M0, LOW);
  digitalWrite(PIN_M1, LOW);

  LORA.begin(9600, SERIAL_8N1, E32_RX_PIN, E32_TX_PIN);

  Wire.begin(21, 22);

  if (!aht.begin()) {
    Serial.println("No se detecta AHT20");
    while (1);
  }

  Serial.println("Nodo con AHT20 listo");
}





void loop() {
  float sumH = 0.0;
  float sumT = 0.0;
  const int N = 6;  // 6 medidas * 10s = 60s

  for (int i = 0; i < N; i++) {
    sensors_event_t humidity, temp;
    aht.getEvent(&humidity, &temp);

    sumH += humidity.relative_humidity;
    sumT += temp.temperature;

    delay(10000); // cada 10 segundos
  }

  float hAvg = sumH / N;
  float tAvg = sumT / N;

  String msg = "TEST," + String(hAvg, 2) + "," + String(tAvg, 2);
  LORA.println(msg);
  Serial.println("Enviado: " + msg);
}
