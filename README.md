# Garmin Connect Personal API für Home Assistant

Custom-Integration (HACS), die **alle 26 lesenden Endpunkte** der offiziellen
Garmin Connect Personal API bereitstellt: als Sensoren für die Standardwerte und
als Services für alles andere. Es werden keine Werte berechnet oder erfunden –
was Garmin nicht liefert, bleibt leer (`unbekannt`).

> **Stand:** v0.1.0, geschrieben ohne Zugriff auf einen Garmin-Account und ohne
> laufendes Home Assistant. Getestet ist die Logik (Token, Retry, Zeitfenster,
> Filter, Wert-Extraktion, Sensorliste) mit simulierten Antworten. Die Feldnamen
> stammen aus dem Swagger/den dokumentierten Modellen und aus
> `thomascamminady/gcpapi-sync`. **Erster echter Lauf: bitte Diagnose und Log
> prüfen** und leere Sensoren melden.

## Installation

1. HACS → Benutzerdefinierte Repositories → dieses Repository als *Integration* hinzufügen.
2. Installieren, Home Assistant neu starten.
3. Auf <https://connect.garmin.com/app/settings/personalApiToken> einen Schlüssel erzeugen
   (Garmin zeigt ihn **nur einmal**) und die gewählte Gültigkeit merken.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → *Garmin Connect Personal API*.
   Für jede Person eine eigene Instanz mit eigenem Schlüssel anlegen.

Der Schlüssel liegt nur in Home Assistant. Gib ihn nirgends sonst ein.

## Schlüssel-Ablauf

Garmin verrät das Ablaufdatum nicht über die API. Die Integration rechnet ab dem
Anlegen mit der gewählten Gültigkeit (30/90/180/365 Tage), zeigt ein Diagnose-Sensor
„API-Schlüssel läuft ab“ und legt **7 Tage vorher** einen Reparatur-Hinweis an.
Erneuern: neuen Schlüssel erzeugen → am Eintrag *Neu konfigurieren*. Wird der Schlüssel
vorher abgelehnt, startet Home Assistant automatisch die Neu-Anmeldung.

## Sensoren (~100)

Gruppiert nach Abrufintervall (Standard in Klammern):

| Gruppe | Inhalt |
|---|---|
| Tageswerte (15 min) | Schritte, Distanz, Kalorien, Intensitätsminuten, Stockwerke, Puls (Ruhe/Min/Max), Stress, Body Battery, SpO2, Atmung, Trinkmenge, letzte Synchronisation |
| Schlaf & HRV (60 min) | Dauer, Phasen, Schlafwert + Teilwerte, Beginn/Ende, Schlafbedarf, HRV letzte Nacht/Woche/Status |
| Körper (60 min) | Gewicht, BMI, Körperfett/-wasser, Muskel-/Knochenmasse, Fitnessalter |
| Aktivitäten (30 min) | Letzte Aktivität (Name, Typ, Start, Distanz, Dauer, Kalorien, Puls, Trainingseffekt, Belastung, VO2max, Höhenmeter), Wellness-Aktivitäten |
| Profil (24 h) | Konto, eingestellte Herzfrequenzzonen |

Viele Detailsensoren sind standardmäßig **deaktiviert** und können einzeln aktiviert werden.
Beim ersten vollständigen Abruf werden außerdem einmalig die Sensoren deaktiviert, für die Garmin
zwar den Endpunkt beantwortet, aber keinen Wert für das Feld liefert (z. B. Körperfett ohne
Körperanalyse-Waage). Endpunkte, die noch gar nichts geliefert haben (z. B. Schlaf am frühen Morgen),
bleiben unberührt. Wieder einschalten geht jederzeit unter Einstellungen → Entitäten.
Zusätzlich: Binary-Sensor *Uhr-Synchronisation überfällig* und Event-Entität *Aktivität*
(feuert `activity_finished` bei jeder neuen Aktivität, nicht beim ersten Start).

Optionen: Intervall der Tageswerte, Sync-Warnschwelle, und ob Tagesverläufe
(Puls, Body Battery, SpO2) als Attribute angehängt werden (groß, nicht im Recorder gespeichert).
Nur mit dieser Option werden die zusätzlichen Endpunkte für Puls- und Body-Battery-Verlauf abgefragt.

Abrufmenge mit den Standardwerten: etwa 480 Anfragen pro Tag und Konto (ohne Tagesverläufe).
Garmin nennt für die Personal API keine Limits und bietet keinen Push; es wird nur abgefragt.

Nicht in der Personal API enthalten (und deshalb nicht vorhanden): Training Readiness,
Trainingsstatus, VO2max als Tageswert, Race Predictions. VO2max gibt es nur je Aktivität.

## Services (Antwort als Daten, z. B. für Skripte und Templates)

* `garmin_personal.fetch` – jeder Endpunkt per Kurzname (`daily_summary`, `sleep`, `hrv_summaries`,
  `stress`, `menstrual_summary`, `nutrition`, `activity`, …) für Tag oder Zeitraum. Lange Zeiträume
  werden automatisch in Garmins erlaubte Fenster zerlegt.
* `garmin_personal.search_activities` – Filter wie `activity_type`, `min_distance`, `start_date`,
  `bounding_box`, mit automatischem Blättern.
* `garmin_personal.download_activity` – Original-ZIP (FIT) in einen erlaubten Ordner.
* `garmin_personal.backfill_statistics` – schreibt Tageswerte (Schritte, Puls, Stress, Body Battery,
  Kalorien …) rückwirkend in die **Langzeitstatistik** (externe Statistik `garmin_personal:<entry>_<name>`,
  ein Wert pro Tag). Wiederholbar, überschreibt dieselben Tage.

## Datenschutz

Gesundheitsdaten. Menstruations- und Ernährungsdaten gibt es **nur** über Services auf ausdrücklichen
Abruf, nie als Sensor. Die Diagnose enthält weder Schlüssel noch Messwerte.

## Garmin-Eigenheiten, die berücksichtigt sind

Zeitraumgrenzen (Schritte/Stress 28 Tage, Schlaf/Hydration/Body Battery 31 Tage, HRV 365 Tage),
maximal ~45 Aktivitäten je Seite, Wiederholung bei 429/5xx mit `Retry-After`, ein erneuter
Token-Tausch bei 401, Zeitstempel als ISO oder Millisekunden. `weight/all` liefert bei Garmin
derzeit immer HTTP 400 und ist nur der Vollständigkeit halber über `fetch` erreichbar.

## Entwicklung

```
python3 -I tests/test_api.py && python3 -I tests/test_values.py && python3 -I tests/test_sensors.py
python3 -I scripts/gen_translations.py   # erzeugt strings.json und translations/
```
Die Tests brauchen weder Home Assistant noch Netzwerk.

Persönliche Nutzung laut Garmin-Bedingungen der Personal API.
