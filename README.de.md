# Garmin Connect Personal API für Home Assistant

*[English version](README.md)*

Custom-Integration (HACS), die **alle 26 lesenden Pfade** (25 Datenendpunkte und den Download einer Aktivitätsdatei) der offiziellen Garmin Connect Personal API bereitstellt: als Sensoren für die Standardwerte und als Services für alles andere. Es werden keine Werte berechnet oder erfunden – was Garmin nicht liefert, bleibt leer (`unbekannt`). Die einzige Ausnahme ist das Ablaufdatum des API-Schlüssels, das Garmin nicht verrät und das lokal gezählt wird (siehe „Schlüssel-Ablauf“).

> **Stand:** läuft gegen einen echten Garmin-Account in Home Assistant (aktuelle Version: siehe `manifest.json` und
> das [Changelog](CHANGELOG.md), das englisch ist). Die Logik (Token, Retry, Zeitfenster, Filter, Wert-Extraktion,
> Sensorliste) ist mit simulierten Antworten getestet. Die Feldnamen stammen aus dem Swagger, den dokumentierten
> Modellen und echten Antworten. Sensoren, die dauerhaft leer bleiben, bitte mit Diagnose und Log melden.

## Installation

1. HACS → Benutzerdefinierte Repositories → dieses Repository als *Integration* hinzufügen.
2. Installieren, Home Assistant neu starten.
3. Auf <https://connect.garmin.com/app/settings/personalApiToken> einen Schlüssel erzeugen
   (Garmin zeigt ihn **nur einmal**) und die gewählte Gültigkeit merken.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → *Garmin Connect Personal API*.
   Für jede Person eine eigene Instanz mit eigenem Schlüssel anlegen.

Der Schlüssel liegt nur in Home Assistant. Gib ihn nirgends sonst ein. Ein Name ist Pflicht (es gibt keinen
Standardwert); er wird Gerätename und Teil der Entitäts-IDs. Das Konto wird an Garmins interner Profil-ID erkannt;
Umbenennen oder ein geänderter Garmin-Anzeigename spielt keine Rolle. Einträge aus früheren Versionen werden beim
ersten Start nach dem Update automatisch umgestellt, Entitäten und Verlauf bleiben. Home Assistant 2025.10.0 oder
neuer ist nötig.

## Was du nach der Einrichtung siehst

* Pro Konto ein **Gerät**, benannt wie das Konto (zum Beispiel „Alex“), mit rund 120 Sensoren, einem Binärsensor,
  einer Event-Entität und einem Kalender. Etwa die Hälfte der Sensoren ist **standardmäßig aktiv**; der Rest sind
  Detailwerte, die du unter Einstellungen → Entitäten einschalten kannst.
* Die Entitäts-IDs setzen sich aus Gerätename und Sensorname in der Sprache zusammen, die Home Assistant beim Anlegen
  der Entität benutzt hat, zum Beispiel `sensor.alex_schritte` (Deutsch) oder `sensor.alex_steps` (Englisch). Sieh sie
  unter Einstellungen → Entitäten nach; die Beispiele unten nutzen solche Namen.
* Werte erscheinen nach dem ersten Abruf. Manche Sensoren bleiben leer, bis Garmin etwas liefert (Schlaf am frühen
  Morgen, Körperwerte ohne Waage). Kurz nach dem ersten vollständigen Abruf werden Sensoren, für die Garmin gar keinen
  Wert liefert, einmalig deaktiviert (siehe unten).
* Die Live-Sensoren haben **keinen Verlauf vor dem Zeitpunkt ihrer Erstellung**. Ältere Tage bekommst du mit
  `garmin_personal.backfill_statistics` einmalig in die Diagramme (siehe „Verlauf und Langzeitstatistik“).

## Zwei Personen (ein Eintrag pro Person)

Lege die Integration einmal pro Person an, jeweils mit dem eigenen Schlüssel und einem anderen Namen („Alex“, „Sam“).
Jeder Eintrag hat sein eigenes Gerät, seine Sensoren, sein Event und seinen Kalender; die Entitätsnamen tragen den
Namen der Person. Services wirken auf **ein** Konto: Bei mehreren Konten musst du es im Feld *Konto* wählen (Beispiel
unter Services). Die Schlüssel laufen unabhängig ab; jeder Eintrag hat einen eigenen Sensor „API-Schlüssel läuft ab“
und eine eigene Reparatur-Meldung.

## Schlüssel-Ablauf

Garmin verrät das Ablaufdatum nicht über die API. Das angezeigte Datum ist deshalb **berechnet**, nicht von Garmin
gelesen: Die Integration zählt ab dem Anlegen mit der gewählten Gültigkeit (30/90/180/365 Tage). Wähle dieselbe
Gültigkeit wie bei Garmin, sonst stimmt das Datum nicht und die Warnung kommt zu spät oder zu früh. Ein
Diagnose-Sensor „API-Schlüssel läuft ab“ zeigt das berechnete Datum (er arbeitet lokal und hängt nicht an der
Verbindung zu Garmin), und **7 Tage vorher** erscheint ein Reparatur-Hinweis (stündlich geprüft), der nach dem Datum zum
Fehler wird. Erneuern: neuen Schlüssel erzeugen → am Eintrag *Neu konfigurieren*. Wird der Schlüssel vorher abgelehnt, startet Home Assistant automatisch die erneute Authentifizierung.

**Schlüssel und Token.** Der Schlüssel, den du bei Garmin erzeugst, wird gegen ein Zugriffstoken getauscht, das **24 Stunden**
gilt. Es gibt kein Refresh-Token: Die Integration tauscht den Schlüssel neu, wenn das Token abläuft oder Garmin es
ablehnt (HTTP 401). Der Schlüssel selbst gilt 30, 90, 180 oder 365 Tage (deine Wahl bei Garmin); Garmin schickt etwa
**eine Woche vorher** eine E-Mail, und diese Integration zeigt 7 Tage vor dem berechneten Datum ihre Reparatur-Meldung.
Garmin zeigt den Schlüssel **nur einmal**: Ging er verloren, erzeuge einen neuen (der alte bleibt bis zum Ablauf gültig
oder bis du ihn bei Garmin widerrufst) und nutze *Neu konfigurieren*; Entitäten und Verlauf bleiben erhalten. Wähle
beim Erneuern die Gültigkeit des neuen Schlüssels wieder aus, denn sie bestimmt das berechnete Datum.

## Sensoren (~120)

Abruf: Der Tageswert (mit der Zeit des letzten Uhr-Syncs) wird alle 5 Minuten abgefragt, das ist eine
einzige Anfrage. Nur wenn sich die Sync-Zeit ändert, werden SpO2, Flüssigkeitszufuhr, Schlaf, Körperwerte und
Aktivitäten geholt. Zusätzlich gibt es einen Fallback (Tageswerte stündlich, Schlaf alle 2 Stunden,
Körperwerte und Aktivitäten stündlich) für Daten, die ohne Uhr-Sync entstehen, z. B. Waage oder App-Einträge.

| Gruppe | Inhalt |
|---|---|
| Tageswerte (Tageswert 5 min, Rest bei neuem Sync / stündlich) | Schritte, Distanz, Kalorien, Intensitätsminuten, Stockwerke, Puls (Ruhe/Min/Max), Stress, Body Battery, SpO2, Atmung, Flüssigkeitszufuhr, letzte Synchronisation |
| Schlaf & HRV (bei neuem Sync, sonst 2 h) | Dauer, Phasen, Schlafwert + Teilwerte, Beginn/Ende, Schlafbedarf, HRV letzte Nacht/Woche/Status |
| Körper (bei neuem Sync, sonst 1 h) | Gewicht, BMI, Körperfett/-wasser, Muskel-/Knochenmasse, Fitnessalter |
| Aktivitäten (bei neuem Sync, sonst 1 h) | Letzte Aktivität (Name, Typ, Start, Distanz, Dauer, Kalorien, Puls, Trainingseffekt, Belastung, VO2max, Höhenmeter), Wellness-Aktivitäten |
| Profil (24 h) | Konto, eingestellte Herzfrequenzzonen |

Viele Detailsensoren sind standardmäßig **deaktiviert** und können einzeln aktiviert werden.
Beim ersten vollständigen Abruf werden außerdem einmalig die Sensoren deaktiviert, für die Garmin
zwar den Endpunkt beantwortet, aber keinen Wert für das Feld liefert (z. B. Körperfett ohne
Körperanalyse-Waage). Endpunkte, die noch gar nichts geliefert haben (z. B. Schlaf am frühen Morgen),
bleiben unberührt. Das gilt nur für Körper- und Profilsensoren (nie für die Sensoren der *letzten Aktivität*, die nur die neueste Aktivität beschreiben), erst wenn der Eintrag mindestens 24 Stunden alt
ist und die Uhr am selben Tag synchronisiert hat; die Schlüssel stehen im Log auf Info-Ebene. Wieder einschalten geht
jederzeit unter Einstellungen → Entitäten.
Zusätzlich: Binärsensor *Uhr-Synchronisation überfällig* und Event-Entität *Aktivität*.

**Das Event feuert, nachdem die Uhr synchronisiert hat**, wenn Garmin Connect eine neue Aktivität auflistet
(Ereignistyp `activity_finished`), nicht in dem Moment, in dem das Training endet; dazwischen können Stunden liegen.
Aktivitäten, die während eines Neustarts von Home Assistant auftauchten, werden nach dem Start gemeldet. Bei einem
neuen Konto wird beim ersten Abruf nichts gemeldet, und eine leere erste Antwort von Garmin setzt keinen Startpunkt.
Die Ereignisdaten (Attribute der
Event-Entität) enthalten `activity_id`, `name`, `type`, `start_time_gmt`, `distance` (Meter), `duration` (Sekunden)
und `calories`.

Außerdem: eine **Kalender**-Entität mit den letzten Aktivitäten (rund 20, aus Garmins Startzeit und, falls Garmin sie liefert, der
verstrichenen Dauer; Distanz in deinem Einheitensystem, Kalorien und Durchschnittspuls in der Beschreibung; als
aktuelles Ereignis zeigt die Entität nur eine laufende oder die nächste kommende Aktivität), standardmäßig deaktivierte Sensoren für Stressanteile,
durchschnittliche Höhe, höchste/niedrigste Atmung, niedrigsten/höchsten Durchschnittspuls, die Body-Battery-Stufe (Garmins Feedback und Ereignisliste als Attribute), *Pulsalarme* (Garmins Zähler je Tag; die obere und untere Alarmschwelle erscheinen als Attribute, wenn die Pulsantwort des Tages abgefragt wird), Durchschnitts- und Höchstgeschwindigkeit der letzten Aktivität und die Schlaf-Ausrichtung mit Garmins empfohlenem Fenster
(Minuten nach Mitternacht, wie geliefert).

Optionen: Abrufintervall der Tageswerte (das ist die Sync-Prüfung), Sync-Warnschwelle, und ob Tagesverläufe
(Puls, Body Battery, SpO2) als Attribute angehängt werden (groß, nicht im Recorder gespeichert).
Nur mit dieser Option werden die zusätzlichen Endpunkte für Puls- und Body-Battery-Verlauf für die Sensoren abgefragt.

Die Option **Stundenstatistik schreiben** (standardmäßig an) ist davon unabhängig: Nach jeder neuen Uhr-Synchronisierung
schreibt sie Puls, Body Battery und SpO2 als Stundenwerte in die Langzeitstatistik (siehe „Verlauf und
Langzeitstatistik“). Sie nutzt die ohnehin laufenden Abrufe und fragt sonst je Reihe einmal zusätzlich.

Die Option **Verlauf automatisch nachtragen** (standardmäßig an) hängt die echten Messpunkte an die (Verlauf)-Sensoren,
die du aktiviert hast; siehe `backfill_history` unten. Ohne aktivierten und aufgezeichneten Verlauf-Sensor tut sie
nichts.

Einheiten: Distanzen sind in Metern, Dauern in Sekunden, Geschwindigkeiten in m/s (die optionalen Sensoren *Letzte Aktivität: Durchschnitts-/Höchstgeschwindigkeit* werden standardmäßig in km/h angezeigt), Trinkmenge in mL, Puls in bpm, Atmung in Atemzügen pro Minute, SpO2 und Body Battery in Prozent bzw. 0-100. Die Einheit steht am Sensor, und eine Dashboard-Karte kann umrechnen. Schlafbedarf in Minuten und HRV in ms sind die üblichen Einheiten, aber eine Beobachtung: Die Spezifikation nennt dafür keine Einheit. **Gewicht und Körpermassen werden in kg angezeigt. Garmins Spezifikation sagt Kilogramm, echte Antworten enthalten aber Gramm; die Integration teilt durch 1000** (an einer echten Wiegung geprüft). Attribute behalten Garmins eigene Werte und Einheiten: `averageSpeed` und `maxSpeed` von *Letzte Aktivität* sind m/s, `elevationGain`/`elevationLoss` Meter, Leistung Watt, `hrTimeInZone_1` bis `_5` und `fastestSplit_*` Sekunden, die Verlaufs-Attribute Paare `[Zeit in ms (UTC), Wert]`, `weight_delta_g` Gramm, die `*_min`-Attribute der Schlafausrichtung Minuten nach Mitternacht. Viele „heute“-Werte (Schritte, minimaler/maximaler Puls) beginnen um Mitternacht neu.

Abrufmenge: etwa 290 Anfragen pro Tag und Konto für die Sync-Prüfung, dazu etwa 9 je Uhr-Sync
und die Fallbacks, insgesamt grob 400 bis 500 (ohne Tagesverläufe). Die Stundenstatistik fügt etwa 2 Anfragen je
Uhr-Sync hinzu (Puls und Body Battery von heute; SpO2 wird ohnehin abgefragt) und 3 für gestern beim ersten
vollständigen Abruf eines Tages und nach jedem Sync vor 10 Uhr Ortszeit, also grob 30 bis 60 mehr pro Tag. Bei
eingeschalteten Tagesverläufen als Attribute werden die Reihen von heute ohnehin geholt, es bleiben nur die 3 für gestern.
Garmin nennt für die Personal API keine Limits und bietet keinen Push; es wird nur abgefragt.

Die Personal API kennt keine Training Readiness, keinen Trainingsstatus, kein VO2max als Tageswert und keine Rennprognosen (VO2max gibt es nur je Aktivität); die vollständige Liste steht unter „Endpunkte und Services“.

Schlaf-, HRV- und Körper-Sensoren behalten den **letzten bekannten Wert**, solange Garmin nichts liefert (z. B. am
Morgen, bevor die neue Nacht synchronisiert ist), auch über einen Neustart. Die Attribute `held_value` (wahr, solange
der Wert alt ist) und `last_seen` (wann dieser Wert zuerst hier ankam, nicht wann er gemessen wurde) zeigen das an. Es wird nichts
geschätzt. In der Langzeitstatistik läuft ein gehaltener Wert als flache Linie weiter; für exakte Tageswerte nimm
`backfill_statistics`. Ist Garmin kurz nicht erreichbar, behalten alle Sensoren ihre letzten Werte (Tageswerte nie über
Mitternacht hinweg); nach etwa 15 Minuten (oder drei Abrufintervallen) ohne erfolgreichen Abruf werden sie
nicht verfügbar. Nullwerte, negative Werte und Platzhalter, die Garmin für „nicht gemessen“ schickt (zum Beispiel
Gewicht 0 oder eine Nacht mit 0 Sekunden), gelten als kein Wert. Die Gewichtssensoren ignorieren Einträge, die nur
eine Profiländerung sind.

Die Zonen-Untergrenzen (untere Pulsgrenzen der Zonen 1 bis 5) sind Attribute von *Maximaler Puls (eingestellt)*; der
Fitnessalter-Sensor hat Garmins `previous_fitness_age` als Attribut. Garmin beschreibt die Antwort zum Fitnessalter als
Liste von Datensätzen (frühere Antworten waren ein einzelnes Objekt): Beides wird gelesen, aus einer Liste der neueste
Datensatz mit Fitnessalter. Die Anfrage sendet `fullHistoryScan=false`, Garmin sucht also nur in den letzten 28 Tagen vor
dem Datum: Gab es in dieser Zeit keinen neuen Wert, enthält die Antwort einen `invalidReason` und die Fitnessalter-Sensoren
bleiben leer. (`fetch` mit `full_history_scan: true` zeigt, was Garmin im gesamten Verlauf hat.)

## Endpunkte und Services

Die Integration deckt alle 26 Pfade der Spezifikation der Garmin Connect Personal API ab
(`docs/garmin-personal-swagger.json`, Version 1.0.0): 25 Datenendpunkte, abrufbar mit dem Service
`garmin_personal.fetch` unter dem Kurznamen aus der Tabelle, und den Download einer Aktivitätsdatei
(`garmin_personal.download_activity`). Alles ist nur lesend (alle Pfade sind GET). Die Tabelle wird aus dem Code erzeugt
(`scripts/api_fields.py --write-readme`); das Limit ist der längste Zeitraum je Anfrage, längere Zeiträume werden
automatisch geteilt. *Spec* kennzeichnet Limits aus Garmins Spezifikation, *beobachtet* Limits, die am echten Dienst
gemessen wurden und sich ändern können.

<!-- endpoints:start (generated by scripts/api_fields.py --write-readme) -->

| Endpunkt | Kurzname / Dienst | Größter Zeitraum je Anfrage | Entitäten und Attribute | Aktualisierung |
|---|---|---|---|---|
| `/activity-service/activity/{activityId}` | `activity` | – | nur Dienst | bei Aufruf |
| `/activity-service/activity/{activityId}/workouts` | `activity_workouts` | – | nur Dienst | bei Aufruf |
| `/activitylist-service/activities/search/activities` | `activities` | etwa 45 je Seite (beobachtet) | Sensoren *Letzte Aktivität* samt Attributen, Ereignis *Aktivität*, Kalender | neuer Sync, sonst 1 h |
| `/biometric-service/heartRateZones/v2` | `hr_zones` | – | Max-, Ruhe- und Laktatschwellenpuls; Zonen-Untergrenzen als Attribute von *Maximaler Puls (eingestellt)* | 24 h |
| `/download-service/files/activity/{activityId}` | `download_activity` | – | Dienst `download_activity` (ZIP mit der FIT-Datei) | bei Aufruf |
| `/fitnessage-service/fitnessage/v2/{calendarDate}` | `fitness_age` | 28 Tage Rückschau (Spec) | Fitnessalter, erreichbares und tatsächliches Alter; Attribute `previous_fitness_age`, `components` | neuer Sync, sonst 1 h |
| `/goal-service/goal/user/effective/weightgoal/{startDate}/{endDate}` | `weight_goals` | – | nur Dienst | bei Aufruf |
| `/hrv-service/hrv/{calendarDate}` | `hrv` | 1 Tag (Spec) | *HRV (Verlauf)* (nächtliche Einzelwerte) | neuer Sync, mit der Verlauf-Option |
| `/hrv-service/hrv/daily/{fromDate}/{toDate}` | `hrv_summaries` | 365 Tage (beobachtet) | HRV letzte Nacht, Woche, 5-Minuten-Höchstwert, Status, Feedback | neuer Sync, sonst 2 h |
| `/nutrition-service/food/logs/{date}` | `nutrition` | 1 Tag (Spec) | bewusst kein Sensor (nur Dienst) | bei Aufruf |
| `/periodichealth-service/menstrualcycle/summary/{calendarDate}` | `menstrual_summary` | 1 Tag (Spec) | bewusst kein Sensor (nur Dienst) | bei Aufruf |
| `/periodichealth-service/menstrualcycle/dayview/{calendarDate}` | `menstrual_day` | 1 Tag (Spec) | bewusst kein Sensor (nur Dienst) | bei Aufruf |
| `/sleep-service/sleep/dailySleep` | `sleep` | 1 Tag (Spec) | Schlafsensoren (Dauer, Phasen, Score und Teilscores, Start/Ende, Bedarf, Ausrichtung, Atmung) | neuer Sync, sonst 2 h |
| `/sleep-service/sleep/dailySleepSummariesByDate` | `sleep_summaries` | 31 Tage (Spec) | Statistik-Import `backfill_statistics` | bei Aufruf |
| `/userprofile-service/userprofile/settings` | `profile` | – | *Konto* (Attribute: Sprache, Einheiten, Zeitzone, ...) | 24 h |
| `/usersummary-service/stats/hydration/daily/{startDate}/{endDate}` | `hydration` | 31 Tage (Spec) | Trinkmenge, Ziel, Schweißverlust | neuer Sync, sonst 1 h |
| `/usersummary-service/stats/steps/daily/{startDate}/{endDate}` | `steps` | 28 Tage (Spec) | nur Dienst: Tagessummen (keine Werte innerhalb des Tages) | bei Aufruf |
| `/usersummary-service/stats/stress/daily/{startDate}/{endDate}` | `stress` | 28 Tage (Spec) | nur Dienst: Tageswerte (keine Stresskurve) | bei Aufruf |
| `/usersummary-service/usersummary/daily` | `daily_summary` | 1 Tag (Spec) | Tagessensoren: Schritte, Distanz, Kalorien, Intensitätsminuten, Stockwerke, Puls, Stress, Body Battery, Atmung, Pulsalarme, letzte Synchronisation | alle 5 min (Sync-Prüfung) |
| `/usersummary-service/v2/dailysummaries` | `daily_summaries` | 31 Tage (Spec: 1 Jahr) (Code) | Statistik-Import `backfill_statistics` | bei Aufruf |
| `/weight-service/weight/all/{startDate}/{endDate}` | `weights_all` | – | nur Dienst; Garmin antwortet derzeit mit HTTP 400 | bei Aufruf |
| `/weight-service/weight/range/{startDate}/{endDate}` | `weight_range` | 360 Tage (beobachtet) | Gewicht, BMI, Körperfett/-wasser, Muskel-/Knochenmasse, Viszeralfett, Stoffwechselalter | neuer Sync, sonst 1 h (90 Tage) |
| `/wellness-service/wellness/bodyBattery/reports/daily` | `body_battery` | 31 Tage (Spec) | Body-Battery-Verlauf (Attribut, Stundenstatistik, *Body Battery (Verlauf)*) | neuer Sync, mit Intraday-, Stunden- oder Verlauf-Option |
| `/wellness-service/wellness/daily/spo2acclimation/{calendarDate}` | `spo2` | 1 Tag (Spec) | SpO2 Mittel, Tiefstwert, aktuell, 7 Tage; SpO2-Stundenreihe | neuer Sync, sonst 1 h |
| `/wellness-service/wellness/dailyHeartRate` | `heart_rate` | 1 Tag (Spec) | Pulsverlauf (Attribut, Stundenstatistik, *Puls (Verlauf)*); Alarmschwellen als Attribute von *Pulsalarme* | neuer Sync, mit Intraday-, Stunden- oder Verlauf-Option |
| `/wellnessactivity-service/activity/summary/range/{fromDate}/{untilDate}` | `wellness_activities` | 31 Tage (beobachtet) | *Wellness-Aktivitäten heute* (Anzahl) | neuer Sync, sonst 1 h |

<!-- endpoints:end -->

**Schritte gibt es nur als Tagessumme.** Die Personal API von Garmin liefert Schritte (und Strecke und Stockwerke) einmal
pro Kalendertag, nichts innerhalb des Tages; die Spezifikation wurde dazu geprüft. Der Sensor *Schritte* zählt deshalb im
Tagesverlauf hoch und beginnt nach Mitternacht wieder bei 0. Einen Verlauf über den Tag gibt es nur, soweit Home Assistant
den Sensor aufzeichnet; die Auflösung ist der Abstand zwischen zwei Uhr-Synchronisierungen, keine Minutenkurve wie in der
Garmin-App. Es wird nichts geschätzt oder aufgefüllt.

**Gibt es nicht (die Spezifikation ist die Grenze).** Die Personal API kennt keine: Schritte im Tagesverlauf, Zeitreihen
für Stress, Schlafphasen oder Atmung (nur Tageswerte; Puls-, Body-Battery-, SpO2- und HRV-Verläufe gibt es), Training
Readiness, Trainingsstatus, VO2max als Tageswert (nur je Aktivität), Rennprognosen, Endurance- oder Hill-Score, Blutdruck,
Geräte- oder Akkudaten, Ausrüstung, Roh-Streams einer Aktivität (dafür der FIT-Download), Webhooks oder Push und keinen
Schreibzugriff. Was nicht in der Spezifikation steht, kann die Integration nicht anzeigen.

Benachrichtigung nach einer neuen Aktivität:

```yaml
alias: Garmin-Aktivität melden
triggers:
  - trigger: state
    entity_id: event.alex_aktivitat
actions:
  - action: notify.notify
    data:
      message: >-
        Neue Aktivität: {{ trigger.to_state.attributes.name }},
        {{ (trigger.to_state.attributes.distance / 1000) | round(1) }} km
```

Warnung, wenn die Uhr länger nicht synchronisiert hat: den Binärsensor *Uhr-Synchronisation überfällig* als Auslöser
nehmen; die Schwelle stellst du in den Optionen ein.

Dashboard: Eine *Statistik-Diagramm*-Karte oder eine einfache Entitätenkarte mit `sensor.alex_schritte`,
`sensor.alex_schlafwert` und `sensor.alex_ruhepuls` zeigt die wichtigsten Werte.

## Services (Antwort als Daten, z. B. für Skripte und Templates)

Alle Services sind **nur für Administratoren** (sie liefern Gesundheitsdaten, schreiben Dateien und Statistiken).
Automationen und Skripte rufen sie wie gewohnt auf; ein normales Benutzerkonto kann das nicht.

Bei **mehreren Konten** braucht jeder Service das Feld *Konto*. Im Formular wählst du es aus einer Liste; in YAML ist
es die Config-Entry-ID (Service-Formular öffnen, Konto wählen, in den YAML-Modus wechseln und den Wert kopieren).
Beispiel mit Antwort:

```yaml
action: garmin_personal.fetch
data:
  config_entry_id: <entry_id>
  endpoint: sleep
  date: "2026-01-15"
response_variable: result
```

Bei genau einem Konto darf das Feld fehlen. Fehlt es bei mehreren Konten, bricht der Service mit einer übersetzten
Fehlermeldung ab, die die Konten auflistet. Alle Service-Fehler sind übersetzt.

* `garmin_personal.fetch` – jeder Endpunkt per Kurzname (`daily_summary`, `sleep`, `hrv_summaries`,
  `stress`, `menstrual_summary`, `nutrition`, `activity`, …) für Tag oder Zeitraum. Lange Zeiträume
  werden automatisch in Garmins erlaubte Fenster zerlegt. Optionale Garmin-Rohparameter für Lesetests (nur gesendet,
  wenn angegeben; ohne Angabe ist die Anfrage die der Sensoren): `chunks` (`body_battery`: Anzahl der Zeitintervalle je
  Tag, Garmin liefert je Intervall den niedrigsten und höchsten Wert), `full_history_scan` (`fitness_age`) und
  `include_all` (`weight_range`: jede Wiegung eines Tages statt der letzten). Eine fehlgeschlagene Anfrage nennt
  Garmins eigene Erklärung bei HTTP 400 (zum Beispiel unbekannter Aktivitätstyp oder zu großer Suchbereich) und bei
  HTTP 404 für eine Aktivität, auf 200 Zeichen gekürzt.
* `garmin_personal.search_activities` – Filter wie `activity_type`, `min_distance`, `start_date`,
  `bounding_box`, mit automatischem Blättern.
* `garmin_personal.download_activity` – Original-ZIP (FIT) in einen Ordner, den Home Assistant erlaubt
  (`allowlist_external_dirs`); Standard `<Medienordner>/garmin_personal/activity_<id>.zip`. Nur `.zip`-Ziele werden
  akzeptiert, bei einem Ordner als Pfad wird der Standard-Dateiname angehängt; sonst meldet der Service, dass der Pfad
  nicht erlaubt ist.
* `garmin_personal.backfill_statistics` – schreibt Tageswerte rückwirkend in die **Langzeitstatistik**
  (externe Statistik `garmin_personal:<entry>_<name>`, ein Wert pro Tag): Aktivität (Schritte, Puls, Stress,
  Body Battery, Kalorien …), Schlaf (Dauer, Phasen, Wert, Puls, Schlafbedarf), HRV und Gewicht/Körperwerte.
  Importiert werden nur echte Garmin-Tage: Tage anderer Quellen und reine Platzhalter-Tage ohne Schritte
  und Puls werden übersprungen, ebenso Gewichtseinträge, die nur eine Profiländerung sind. Mit
  `include_third_party_steps` werden zusätzlich Schritte, Distanz und Stockwerke von Tagen übernommen, die
  andere Apps (z. B. RunGap) in Garmin Connect geschrieben haben. Wiederholbar, überschreibt dieselben Tage. Ohne `end_date`
  endet der Import gestern (heute nur auf ausdrückliche Angabe, weil heute unvollständig ist); höchstens 3650 Tage; er
  läuft in 31-Tage-Fenstern und pro Konto nur ein Import gleichzeitig. Die Antwort nennt nach einer Unterbrechung
  `complete`, `last_completed_day` und `error`, dazu `days_imported`, `statistic_series` und `statistic_rows`. Tage mit
  dem Wert 0 bei Ruhe-/Minimal-/Maximalpuls, Stress, SpO2 oder Atmung werden nicht geschrieben.
  Seit 0.5.8 werden zusätzlich importiert (neue Statistik-IDs, gleiche Namen wie die Live-Sensoren, wo es einen gibt):
  `hydration`, `hydration_goal` (mL), `spo2_average`, `spo2_lowest`, `respiration_lowest`, `respiration_highest`,
  `floors_descended`, `step_goal`, `stress_rest_time`/`_low_time`/`_medium_time`/`_high_time` (Sekunden, Garmin
  liefert Millisekunden), `sleep_spo2_average`/`_lowest`, `sleep_respiration_lowest`/`_highest`, `sleep_need_next`,
  `nap_duration`, `sleep_score_rem`/`_light`/`_deep` (%), `visceral_fat` und `metabolic_age`. Ein Wert, den Garmin
  für einen Tag nicht sendet, wird einfach nicht geschrieben. **Importierte Tage sind nicht in jedem Fall dieselbe
  Größe wie die Live-Sensoren:** In Garmins Format der Tageszusammenfassungen (das der Import nutzt) sind Minimal- und
  Maximalpuls das Minimum und Maximum der *2-Minuten-Mittelwerte* (die Live-Sensoren lesen das absolute Minimum/Maximum),
  `distance` ist nur die Strecke der Schritte (der Live-Sensor addiert die Aktivitätsstrecke), und `respiration_average`
  ist der Tagesmittelwert (der Live-Sensor das Mittel im Wachzustand). Bestehende Statistik-IDs wurden nicht geändert;
  vergleiche daher Gleiches mit Gleichem.
* `garmin_personal.backfill_intraday` – schreibt die Tagesverläufe von **Puls, Body Battery und SpO2** rückwirkend als
  **Stundenstatistik** (Minimum, Maximum und Mittelwert je voller Stunde, siehe „Verlauf und Langzeitstatistik“).
  `days` (Standard 7), `start_date` und `end_date` wie oben; ohne `end_date` endet der Import heute (geschrieben
  werden nur abgeschlossene Stunden, nie die laufende), höchstens 366 Tage. Eine Anfrage je Tag und Reihe (3 pro Tag,
  ein Jahr sind also rund 1100 Anfragen: lange Zeiträume in Stücken laufen lassen, falls Garmin mit einem Limit
  antwortet). Wiederholbar; dieselben Stunden werden überschrieben. Pro Konto nur ein Import gleichzeitig (gemeinsam
  mit `backfill_statistics`). Die Antwort nennt nach einer Unterbrechung `complete`, `last_completed_day` und `error`,
  dazu `heart_rate_hours`, `body_battery_hours`, `spo2_hours`, `days_with_data`, `statistic_series` und
  `statistic_rows`; `unknown_format` listet Reihen, deren Antwort diese Version nicht lesen kann.
* `garmin_personal.backfill_history` – schreibt die echten Messpunkte von **Puls, Body Battery, SpO2 und nächtlicher HRV** mit ihren
  eigenen Zeitstempeln als aufgezeichnete Zustände der standardmäßig deaktivierten Diagnose-Sensoren (*Puls (Verlauf)*
  usw.; die Live-Sensoren bekommen nie alte Werte), damit der Bereich Verlauf sie zeigt. `series` (beliebig viele von `heart_rate`, `body_battery`, `spo2`, `hrv`; Standard
  alle), `days` (Standard 7, höchstens 31), `start_date`, `end_date` und `config_entry_id` wie oben.
  Home Assistant kennt keinen unterstützten Weg für historische Zustände: Der Dienst baut `state_changed`-Ereignisse
  mit historischen Zeitstempeln und legt sie in die Warteschlange des Recorders (keine Automation, kein Logbuch, kein
  Websocket-Client sieht sie). Der Weg ist undokumentiert und könnte sich mit einem Home-Assistant-Update ändern. Der
  Sensor muss existieren, aktiviert und aufgezeichnet sein (Einschluss-/Ausschlusseinstellungen des Recorders werden
  beachtet); alte Zeilen räumt `purge_keep_days` ab. Der Dienst ist nur anhängend: Ein dauerhaftes Protokoll je Reihe
  und Tag (genaue Zeitstempel und Werte für die letzten 7 Tage, Anzahl/erster/letzter/Prüfsumme für ältere Tage)
  entscheidet „schon geschrieben?“, nie allein ein letzter Zeitstempel; verspätet synchronisierte ältere Punkte werden
  nachgetragen, geschriebene Punkte nie neu geschrieben, überschrieben oder gelöscht, ein geänderter Wert zu bekanntem
  Zeitstempel wird nur gezählt (`changed_values_skipped`). Ist das Protokoll verloren, wird zuerst der Recorder gelesen;
  ohne diese Prüfung wird nichts geschrieben, außer mit `confirm_rewrite: true` (das kann Zustände verdoppeln). Bricht
  die Übergabe früh ab, werden nur die wirklich übergebenen Punkte vermerkt, und die Antwort nennt
  `history_write_failed: …` mit `complete: false`. Läufe teilen die Sperre mit den anderen Importen und der
  automatischen Variante.

  Jeder Verlauf-Sensor zeigt als Zustand den Wert seines neuesten Messpunkts, die Zeit dieser Messung steht im Attribut
  `measured_at` (ISO, mit Zeitzone). Nur das laufende Nachtragen nach einer Synchronisierung setzt ihn (und der erste
  Lauf nach einem Neuladen, wenn das Protokoll schon Punkte enthält), und nur für einen Punkt, der neuer ist als der
  angezeigte; die Erstladung und Dienstläufe für alte Tage rühren ihn nie an, und nach einem Neustart wird der Wert
  wiederhergestellt. Das kostet eine zusätzliche Zeile je Synchronisierung, geschrieben zur Sync-Zeit mit dem Wert des
  neuesten Punkts (eine Ungenauigkeit von wenigen Minuten ist möglich).

  Hinweise zu den Reihen: *HRV (Verlauf)* trägt Garmins nächtliche HRV-Messwerte (etwa alle 5 Minuten, in ms, vom
  HRV-Endpunkt). Eine Nacht gehört zu dem Tag, an dem du aufwachst; ihre Punkte liegen also am Abend davor und am
  Morgen dieses Tages. Die heutige Nacht wird nach jeder Synchronisierung neu abgefragt und nur noch nicht
  geschriebene Punkte werden angehängt, eine spät vollständige Nacht wird also nicht doppelt geschrieben. Für die HRV
  gibt es keine Stundenstatistik (sie kostete bei jeder Synchronisierung eine weitere Anfrage für reine Nachtdaten).
  *Body Battery (Verlauf)* hat nur die wenigen Punkte pro Tag (etwa 6), die Garmins Personal API bei der hier genutzten Anfrage liefert (die Spezifikation bietet außerdem einen Parameter `chunks`, der den Tag in mehr Intervalle teilt; er wird noch nicht genutzt und lässt sich mit `fetch` ausprobieren), nicht die dichte Kurve aus Garmin Connect; es wird nichts aufgefüllt. SpO2 liest die Spalte `spo2Level`, die Garmins
  Descriptor-Liste nennt (die Umgebungsspalte ist kein SpO2 und wird ignoriert).

  **Automatische Variante** (Option *Verlauf automatisch nachtragen*, standardmäßig an): Sie wirkt nur für eine Reihe,
  deren Verlauf-Sensor aktiviert **und** aufgezeichnet ist (vor jedem Lauf neu geprüft), sonst tut sie still nichts;
  schließt der Recorder einen aktivierten Verlauf-Sensor aus, weist eine Reparaturmeldung darauf hin. Nach jeder
  Synchronisierung werden die neuen Punkte von heute (und von gestern beim ersten vollen Abruf des Tages und nach
  Synchronisierungen vor 10 Uhr) angehängt. Zusätzlich füllt ein Hintergrundlauf die Vergangenheit je Reihe rückwärts ab
  gestern bis zu `keep_days` des Recorders (10, falls unbekannt, höchstens 400): ein Tag nach dem anderen, etwa 20
  Sekunden Abstand, 30 Minuten Pause nach einem Limit und Abbruch nach 14 Tagen ohne Daten in Folge. Erledigte Tage
  werden je Reihe gemerkt, ein Neustart macht also dort weiter, wo er aufgehört hat; heute gilt nie als erledigt, und
  eine später aktivierte Reihe (oder Lücken nach Ausfalltagen) wird beim Neuladen des Eintrags bis zur Grenze
  nachgeladen, ohne vollständige Reihen erneut abzufragen. Der Verlauf-Sensor zeigt den Stand im Attribut
  `history_backfilled_until`. Kosten: eine Anfrage je Reihe und Tag (beim ersten Laden bis zu 3 x `keep_days`, danach
  rund 3 je Synchronisierung zusammen mit der Stundenstatistik, die dieselben Antworten nutzt); die Datenbank wächst um
  einen Zustand je Messpunkt (grob 700 je Reihe und Tag), den der Recorder nach `purge_keep_days` abräumt.

## Übersetzungen

Alle Namen, Services, Dialoge und Hinweise gibt es auf Deutsch und Englisch (`strings.json`, `translations/`,
erzeugt mit `scripts/gen_translations.py`). Feste Wortlisten von Garmin (Bewertung EXCELLENT/GOOD/FAIR/POOR,
HRV-Status, Stressstufe, Aktivitätstyp, Schlaf-Teilwerte, Schlaf-Feedback, Schlaf-Einblick) sind ENUM-Sensoren: Der
Zustand bleibt der englische Schlüssel (z. B. `fair`), die Anzeige wird übersetzt. Schlaf-Teilwerte, Schlaf-Feedback,
Schlaf-Einblick und der persönliche Einblick sind nur für bisher beobachtete Schlüssel übersetzt (wörtlich aus dem
Schlüssel). Unbekannte Werte erscheinen unübersetzt, werden einmalig auf Info-Ebene ins Log geschrieben
(einschalten mit `custom_components.garmin_personal: info` unter `logger:` in der `configuration.yaml`) und nie
ausgeblendet; nichts wird erfunden.
Das HRV-Feedback (`HRV_BALANCED_2` bis `_8`, `ONBOARDING_1`) erscheint als „Ausgeglichen: 6“: Es sind nummerierte
Textvarianten von Garmin, deren Wortlaut die API nicht liefert; angezeigt wird nur die Nummer, keine Deutung und keine Skala. Die Stressstufe hat keinen Zustand „unknown“: Garmins
`UNKNOWN` erscheint als Home Assistants eigener leerer Zustand. Der Sensor *Atemstörungen* hat noch keine Wortliste, weil
die Werte, die Garmin schickt, nicht bekannt sind; jeder gesehene Wert wird unverändert angezeigt und einmal geloggt.

## Verlauf und Langzeitstatistik

* Live-Sensoren erscheinen im Verlauf erst ab dem Zeitpunkt, an dem sie angelegt wurden.
* Rückwirkend importierte Tageswerte (`backfill_statistics`) sind externe Statistiken mit eigenem Namen (Kontoname und
  Wertname) und **getrennt von den Live-Sensoren**: Eine Karte für `sensor.alex_schritte` zeigt importierte Tage
  nicht. Der Bereich *Verlauf* zeigt sie ebenfalls nicht; nimm eine *Statistik-Diagramm*-Karte und wähle die
  importierte Statistik, oder sieh unter Entwicklerwerkzeuge → Statistiken nach (Suche `garmin_personal`). Die Statistik-ID ist
  `garmin_personal:<entry_id>_<name>`, der Anzeigename ist der Kontoname mit dem englischen Wertnamen. Einige Namen
  weichen von den Sensorschlüsseln ab (`sleep_respiration`, `hrv_weekly_average`, `hrv_5_min_high`):

  ```yaml
  type: statistics-graph
  entities:
    - garmin_personal:<entry_id>_steps
  period: day
  stat_types:
    - mean
  ```
* Jeder importierte Tag wird als ein Wert in der ersten Stunde des Tages gespeichert. Mit der Periode *Stunde* zeigt
  eine Karte deshalb eine Spitze um Mitternacht und sonst Lücken; nimm die Periode *Tag*.
* **Stundenwerte** (Puls, Body Battery, SpO2) sind eigene Statistiken mit einem Wert je voller Stunde: Minimum,
  Maximum und Mittelwert der echten Garmin-Messpunkte dieser Stunde (der Mittelwert ist das einfache Mittel der Punkte,
  nicht zeitgewichtet). Sie werden nach jeder neuen Uhr-Synchronisierung geschrieben (Option *Stundenstatistik
  schreiben*) und rückwirkend mit `backfill_intraday`. IDs: `garmin_personal:<entry_id>_heart_rate_hourly`,
  `…_body_battery_hourly`, `…_spo2_hourly` (Einheiten bpm, %, %). Gespeichert werden nur abgeschlossene Stunden, nie die
  laufende; die Stunden von heute und gestern werden nach jedem Sync neu berechnet und überschrieben, spätere
  Korrekturen von Garmin werden also übernommen. Stunden ohne Messung bleiben leer: es wird nichts interpoliert oder
  aufgefüllt, Platzhalterwerte (0 oder negativ bei Puls und SpO2, negativ bei Body Battery) werden verworfen. Gemeint
  sind volle UTC-Stunden. Der Puls hat etwa alle zwei Minuten einen Punkt, eine Stunde also bis zu 30 Punkte; die hier gelesenen SpO2-Werte sind Garmins Stundenmittel (die Spezifikation nennt außerdem einzelne Rohmessungen, `spO2SingleValues`, die noch nicht gelesen werden), Minimum, Maximum und Mittelwert einer SpO2-Stunde sind daher gleich. Zu sehen:
  in einer *Statistik-Diagramm*-Karte (Statistik wählen, Periode *Stunde* oder *Tag*, `stat_types` `min`, `max`,
  `mean`) oder unter Entwicklerwerkzeuge → Statistiken. Im Bereich *Verlauf* erscheinen sie **nicht**, denn der zeigt
  nur Zustände von Entitäten; es sind keine Zustände, sie liegen deshalb weder dort noch in den Attributen.
  In Zeitzonen, deren Abstand zu UTC keine ganze Stundenzahl ist, wird die Stunde um die lokale Mitternacht am Rand
  eines abgerufenen Zeitraums ausgelassen, statt sie aus der Hälfte der Messpunkte zu speichern.

  ```yaml
  type: statistics-graph
  entities:
    - garmin_personal:<entry_id>_heart_rate_hourly
  period: hour
  stat_types:
    - min
    - mean
    - max
  ```

## Änderungen an der Garmin-API erkennen

`docs/api-fields/` enthält die Schlüsselpfade (nur Namen, keine Werte) bekannter Garmin-Antworten.
`scripts/api_fields.py --diff` vergleicht eine frische Antwort damit und listet neue (+) und entfernte (-) Felder.

Die Spezifikation selbst wird ohne Garmin-Konto geprüft: `docs/api-fields/spec-paths.json` enthält die Schlüsselpfade,
die sie je Endpunkt nennt, `scripts/api_fields.py --spec` gibt sie aus, und `--diff-spec ALT NEU` zeigt, was eine neue
Spezifikationsdatei hinzufügt oder entfernt. `tests/test_spec_fields.py` schlägt fehl, wenn sich die Spezifikationsdatei
ändert, ein Pfad keinen Kurznamen hat oder sie ein Feld enthält, das die Integration weder liest noch in
`docs/api-fields/spec-unused.json` als „bewusst nicht genutzt“ führt (die Listen nach dem Ansehen des Unterschieds mit
`--write-spec` neu erzeugen). Spezifikation und echte Antworten weichen in beide Richtungen ab (zum Beispiel ist
`sleepScores` in der Spezifikation leer), deshalb werden beide Arten von Listen getrennt geführt.

## Datenschutz

Gesundheitsdaten. Menstruations- und Ernährungsdaten gibt es **nur** über Services auf ausdrücklichen
Abruf, nie als Sensor. Die Diagnose enthält weder Schlüssel noch Messwerte (auch nicht Konto-ID oder -Namen). Der Sensor *Letzte Aktivität*
trägt Start-Koordinaten, Ortsnamen und Beschreibung der Aktivität als Attribute; sie sind live und in Karten sichtbar,
die Attribute darstellen, aber vom Recorder ausgenommen (wie die Verlaufs-Attribute). Bedenke das beim Teilen von
Dashboards. Auch Service-Antworten können persönliche Daten enthalten (sie stehen auch in Automations-Traces); poste
sie nicht öffentlich. `download_activity` schreibt standardmäßig in den Medienordner; Dateien dort werden nicht ohne
Anmeldung ausgeliefert, anders als im Ordner `www`.

## Garmin-Eigenheiten, die berücksichtigt sind

Zeitraumgrenzen (Schritte/Stress 28 Tage, Schlaf/Hydration/Body Battery 31 Tage laut Spezifikation; `daily_summaries` erlaubt laut Spezifikation ein Jahr, wird aber in 31-Tage-Fenstern abgefragt; HRV 365 Tage und Gewicht 360 Tage beobachtet), maximal ~45 Aktivitäten je Seite (beobachtet), Wiederholung bei 429/5xx mit `Retry-After`, ein erneuter
Token-Tausch bei 401, Zeitstempel als ISO oder Millisekunden. `weight/all` liefert bei Garmin
derzeit immer HTTP 400 und ist nur der Vollständigkeit halber über `fetch` erreichbar.

## Fehlersuche

* **Ein Sensor bleibt `unbekannt`.** Garmin liefert das Feld nicht (zum Beispiel Körperfett ohne Körperanalyse-Waage),
  oder es ist ein Detailsensor, der beim ersten Abruf einmalig deaktiviert wurde. Schalte ihn unter Einstellungen →
  Entitäten ein. Die Diagnose der Integration zeigt, welche Felder Garmin geliefert hat.
* **Schlaf oder HRV ist am Morgen leer.** Die Nacht ist erst nach dem Uhr-Sync verfügbar. Bis dahin behält der Sensor
  den gestrigen Wert; das Attribut `held_value` ist dann wahr.
* **„Garmin hat den Schlüssel abgelehnt“ / erneute Authentifizierung.** Der Schlüssel ist abgelaufen oder widerrufen.
  Erzeuge bei Garmin im selben Garmin-Konto einen neuen und nutze *Neu konfigurieren* (siehe „Schlüssel-Ablauf“).
* **Rate-Limit oder kurze Ausfälle.** Nach HTTP 429 oder einem fehlgeschlagenen Token-Austausch pausiert die Integration
  die Anfragen eine Weile (mit `Retry-After`) und behält die letzten Werte.
* **Synchronisation überfällig.** Die Uhr hat länger als die eingestellten Stunden nicht mit der Garmin-App
  synchronisiert; die Werte bleiben, wie sie sind, bis sie es tut.
* **Mehr Details im Log.** Trage `custom_components.garmin_personal: debug` unter `logger:` → `logs:` ein.

## Entfernen

Lösche den Eintrag unter Einstellungen → Geräte & Dienste. Das entfernt auch den Reparatur-Hinweis und den internen
Merker für die zuletzt gesehene Aktivität. Der Schlüssel bleibt bei Garmin bis zum Ablauf gültig;
widerrufe ihn in Garmin Connect, wenn du ihn nicht mehr brauchst. Mit `backfill_statistics` importierte Statistiken
bleiben in der Datenbank; entferne sie mit dem Service `recorder.clear_statistics` und ihren Statistik-IDs.

## Entwicklung

```
for f in tests/test_*.py; do python3 -I $f || echo FAIL $f; done
python3 -I scripts/gen_translations.py          # erzeugt strings.json, translations/ und icons.json
python3 -I scripts/gen_translations.py --check  # schlägt fehl, wenn die erzeugten Dateien veraltet sind
ruff check .
```
Die CI (`.github/workflows`) führt Tests, `ruff` und hassfest aus; ein Release wird erst danach gebaut.
Starte jede Testdatei in einem eigenen Prozess (die Home-Assistant-Stubs ersetzen Module in `sys.modules`). Die Tests
brauchen weder Home Assistant noch Netzwerk. `strings.json`, `translations/` und `icons.json` nie von Hand ändern;
Namen, Wortlisten und Texte stehen in `scripts/gen_translations.py` und
`custom_components/garmin_personal/labels.py`.

Persönliche Nutzung laut Garmin-Bedingungen der Personal API.
