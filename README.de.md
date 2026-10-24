# Garmin Connect Personal API für Home Assistant

*[English version](README.md)*

Custom-Integration (HACS), die **alle 26 lesenden Endpunkte** der offiziellen
Garmin Connect Personal API bereitstellt: als Sensoren für die Standardwerte und
als Services für alles andere. Es werden keine Werte berechnet oder erfunden –
was Garmin nicht liefert, bleibt leer (`unbekannt`).

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
Fehler wird. Erneuern: neuen Schlüssel erzeugen → am Eintrag *Neu konfigurieren*. Wird der Schlüssel vorher
abgelehnt, startet Home Assistant automatisch die erneute Authentifizierung.

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
bleiben unberührt. Das gilt nur für Körper- und Aktivitätssensoren, erst wenn der Eintrag mindestens 24 Stunden alt
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
durchschnittliche Höhe, höchste/niedrigste Atmung, niedrigsten/höchsten Durchschnittspuls, die Body-Battery-Stufe
(Garmins Feedback und Ereignisliste als Attribute) und die Schlaf-Ausrichtung mit Garmins empfohlenem Fenster
(Minuten nach Mitternacht, wie geliefert).

Optionen: Abrufintervall der Tageswerte (das ist die Sync-Prüfung), Sync-Warnschwelle, und ob Tagesverläufe
(Puls, Body Battery, SpO2) als Attribute angehängt werden (groß, nicht im Recorder gespeichert).
Nur mit dieser Option werden die zusätzlichen Endpunkte für Puls- und Body-Battery-Verlauf abgefragt.

Einheiten: Distanzen sind in Metern und Dauern in Sekunden (Schlafbedarf in Minuten); die Einheit steht am Sensor,
und eine Dashboard-Karte kann umrechnen. Viele „heute“-Werte (Schritte, minimaler/maximaler Puls) beginnen um
Mitternacht neu.

Abrufmenge: etwa 290 Anfragen pro Tag und Konto für die Sync-Prüfung, dazu etwa 9 je Uhr-Sync
und die Fallbacks, insgesamt grob 400 bis 500 (ohne Tagesverläufe).
Garmin nennt für die Personal API keine Limits und bietet keinen Push; es wird nur abgefragt.

Nicht in der Personal API enthalten (und deshalb nicht vorhanden): Training Readiness,
Trainingsstatus, VO2max als Tageswert, Race Predictions. VO2max gibt es nur je Aktivität.

Schlaf-, HRV- und Körper-Sensoren behalten den **letzten bekannten Wert**, solange Garmin nichts liefert (z. B. am
Morgen, bevor die neue Nacht synchronisiert ist), auch über einen Neustart. Die Attribute `held_value` (wahr, solange
der Wert alt ist) und `last_seen` (wann dieser Wert zuerst hier ankam, nicht wann er gemessen wurde) zeigen das an. Es wird nichts
geschätzt. In der Langzeitstatistik läuft ein gehaltener Wert als flache Linie weiter; für exakte Tageswerte nimm
`backfill_statistics`. Ist Garmin kurz nicht erreichbar, behalten alle Sensoren ihre letzten Werte (Tageswerte nie über
Mitternacht hinweg); nach etwa 15 Minuten (oder drei Abrufintervallen) ohne erfolgreichen Abruf werden sie
nicht verfügbar. Nullwerte, negative Werte und Platzhalter, die Garmin für „nicht gemessen“ schickt (zum Beispiel
Gewicht 0 oder eine Nacht mit 0 Sekunden), gelten als kein Wert. Die Gewichtssensoren ignorieren Einträge, die nur
eine Profiländerung sind.

## Beispiele

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
  werden automatisch in Garmins erlaubte Fenster zerlegt.
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
  dem Wert 0 bei Ruhe-/Minimal-/Maximalpuls, Stress oder Atmung werden nicht geschrieben.

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

## Änderungen an der Garmin-API erkennen

`docs/api-fields/` enthält die Schlüsselpfade (nur Namen, keine Werte) bekannter Garmin-Antworten.
`scripts/api_fields.py --diff` vergleicht eine frische Antwort damit und listet neue (+) und entfernte (-) Felder.

## Datenschutz

Gesundheitsdaten. Menstruations- und Ernährungsdaten gibt es **nur** über Services auf ausdrücklichen
Abruf, nie als Sensor. Die Diagnose enthält weder Schlüssel noch Messwerte (auch nicht Konto-ID oder -Namen). Der Sensor *Letzte Aktivität*
trägt Start-Koordinaten, Ortsnamen und Beschreibung der Aktivität als Attribute; sie sind live und in Karten sichtbar,
die Attribute darstellen, aber vom Recorder ausgenommen (wie die Verlaufs-Attribute). Bedenke das beim Teilen von
Dashboards. Auch Service-Antworten können persönliche Daten enthalten (sie stehen auch in Automations-Traces); poste
sie nicht öffentlich. `download_activity` schreibt standardmäßig in den Medienordner; Dateien dort werden nicht ohne
Anmeldung ausgeliefert, anders als im Ordner `www`.

## Garmin-Eigenheiten, die berücksichtigt sind

Zeitraumgrenzen (Schritte/Stress 28 Tage, Schlaf/Hydration/Body Battery 31 Tage, HRV 365 Tage),
maximal ~45 Aktivitäten je Seite, Wiederholung bei 429/5xx mit `Retry-After`, ein erneuter
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
