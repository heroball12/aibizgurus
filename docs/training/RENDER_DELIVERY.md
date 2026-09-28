# Put the Core Academy video folder on Render

The delivery is a complete private folder, `Guru-Core-SDR-Academy`. Keep its names and directory structure intact. It includes all 16 MP4 films, captions, posters, transcripts, field guides, answer keys, a manifest and checksums. Uploading the folder alone does not make lessons official: the app imports it for owner review.

## 1. Deploy the matching application code

The deployment must contain the `training` app, its migrations, all 16 `training/content/moduleN.json` packages, and the `import_training_bundle` management command. Run the project's normal migrations. The importer verifies each delivered lesson against the deployed source; a mismatch stops the import before any records change.

## 2. Add private persistent storage

In the Render web service, attach a persistent disk mounted at `/var/data`. Choose capacity for the delivered folder plus future revisions; check the folder size before choosing a disk. Persistent disks require a paid service. Only files under the mount path survive deploys. Disks are available to the running service, not build/pre-deploy commands; a disk also limits the service to one instance and changes deployment availability. See [Render's persistent disk documentation](https://render.com/docs/disks) for current service behavior and transfer options.

Upload the entire delivery folder into the running service so its manifest is at:

```
/var/data/Guru-Core-SDR-Academy/manifest.json
```

Use Render's supported SSH/SCP transfer or the transfer method in its disk documentation. Obtain the actual SSH connection details from your service dashboard. Do not copy example hostnames or credentials from a tutorial. Run transfers against the live service's disk, not the ephemeral build filesystem.

Set these environment values on the service:

```
TRAINING_MEDIA_ROOT=/var/data/Guru-Core-SDR-Academy
TRAINING_S3_BUCKET=
```

The folder is private application storage. Do not add a public static route, place it under `static/`, or upload answer keys to a public bucket. Existing signed private S3 playback remains an alternative; this bundle import specifically configures disk playback.

## 3. Verify, then import

In the **running web service's Shell**, from the directory containing `manage.py`, run:

```
python manage.py import_training_bundle /var/data/Guru-Core-SDR-Academy --check
python manage.py import_training_bundle /var/data/Guru-Core-SDR-Academy
```

The first command verifies all 16 modules, hashes, file sizes, QA reports, scripts and chapter timings without changing the database. The second creates/updates draft review records, attaches private media and uses the actual film durations and chapters. It never publishes lessons or awards employee credit. Re-running an unchanged import is safe; approved/published versions cannot be silently replaced.

If verification reports a missing file, size/hash mismatch or different deployed curriculum, finish the upload or deploy the matching code and check again. Do not edit the manifest to bypass a mismatch. Do not rename individual files after importing.

## 4. Owner review and employee release

Sign in with the owner account. Open **Training → Manage training → Content**, then preview the Core lessons. Check the real deployed player with sound, captions, chapter seeking, playback beyond five minutes, speed controls, resume and phone layout. Confirm that a signed-out visitor cannot play the private media. A local technical report does not replace this production check.

After accepting a lesson, mark its video, captions and poster assets reviewed in content administration. Use the owner controls to move **Owner review → Approved → Published**. Assign the Core SDR track to employees through the manager workspace. Only published lessons count toward progress; quizzes, reviewed practice and manager practical approval still govern certification.

Keep this delivery and a database backup outside the service as recovery copies. Media folders contain no API credentials. Existing application/Runway/OpenAI credentials remain environment settings in Render, not files in this package.
