# signal_sqlite_md

Convert messages from a Signal SQLite database export to Markdown.

Unlike my [signal_md](https://github.com/thephm/signal_md) which requires output from `signald`, this one requires nothing beyond this Python script, configuration, and a tool to export the DB.

## Disclaimer

I probably should've called it `signal_sqlite_csv_md` because the script doesn't read directly from the SQLite DB, instead it parses a CSV export from it. I tried directly accessing the DB and gave up 🤣

## Context

A big shoutout to Florian Engel whose post `[1]` saved me hours 🤗.

The SQLite DB is encrypted but it's easy to decrypt because you have the key! 

The attachments are not in the DB, they're stored in the file system in a series of folders with 2 digit Hex labels. The files have names like "`000ec9a54abe93416284f83da2f9f8d124778f22191d9422ed9829de2b22c1b7`" with no suffix but don't worry, that info is in the DB and the script takes care of adding the suffix e.g. "`.jpg`".

## Dependencies

The code in this repo relies heavily on my [message_md](https://github.com/thephm/message_md) classes which contain generic `Message`, `Person`, `Group` and other classes and the methods to convert messages to Markdown files. Be sure to read the `README` and the configuration guide for that repo first. 

## References

1. [Extracting Messages from Signal Desktop](https://www.tc3.dev/posts/2021-11-02-extract-messages-from-signal/) by [Florian Engel](https://www.linkedin.com/in/engelflorian) guided my way
2. [DB Browser for SQLite](https://sqlitebrowser.org/dl/) to get your data
3. [message_md](https://github.com/thephm/message_md) upon which this tool depends

## High level process

1. Get your Signal data
2. Configure this tool
3. Run this tool
4. Be happy

## It's your data, go get it!

This section desribes how to get the Signal chat `messages` out of the SQLite database and the identifiers (`conversation-id`) for each person and group.

**Steps**

1. Install DB Browser for SQLite - [2]
	- *NOTE: I had to try multiple older versions before I got one that would open the file*
2. Find the **key** to your SQLite DB, see [1]
    - For me, on Windows, with user `micro` it was here: `C:\Users\micro\AppData\Roaming\Signal\config.json`
3. Find the **path** to your Signal `db.sqlite` database file
    - For me, it was here: `C:\Users\micro\AppData\Roaming\Signal\sql\`
4. Launch "DB Browser for SQLite"
5. Click "Open Database"
6. Choose `Raw key` from the menu to the right of the "Password" field
7. In the "Password" field, type `0x` and then paste the **key** you found in step 2
8. Right click on "messages" and click "Export as CSV file"

![](media/dbbrowser_export_messages.png)

9. Right click on "conversations" and click "Export as CSV file"
10. Find the attachments
    - Mine were under: `C:\Users\micro\AppData\Roaming\Signal\attachments.noindex`
11. Copy the attachments to the same folder (no subfolders) as the CSV file
    - the `cp_signal_attachments.sh` shell script made it easier for me
    - *NOTE: I can improve this later to get the files directly, being lazy!*

## Setting up the config files

The next step is to configure this tool. 

You'll need to define each person that you communicate with in `people.json` and the groups in `groups.json`. This way the tool can associate each message with the person that sent it and who it was sent to.

Samples of these configuration files are in the `message_md` repo [here](https://github.com/thephm/message_md/tree/main/config) upon which this tool [depends](#dependencies).

This part is tedious the first time and needs to be updated when you add new contacts or Groups in Signal, i.e. a pain.

Someday I can automate this but for now, no pain, no gain 🙂. 

The next sections describes where to find the identifiers for people and groups.

### People and groups

1. Open the `conversations.csv` file in your favorite editor
2. Look at the first row
3. If there's a `groupId` field value, that's a group
    - the `name` field will tell you the name of the group

```
""id"":""a1760c87-d3d0-40f6-9992-ac0426efcc14""
""groupId"":""FdibKUgQIZPilWQu3jbgEB+tajc3RUKuoyYNZp4bRhQ=""
""name"":""They get hooked!"
```

4. If there's no `groupID` value, it's a person
    - the `name` field will be the name of the person
    - Find the `id` field

```
""id"":""a1760c87-d3d0-40f6-9992-ac0426efcc15""
""groupId"":""""
""name"":""SpongeBob"
```

5. Add the corresponding row to `groups.json` or `people.json`:
    - set group `id` to the `id` from `conversations.csv`
    - set the `conversation-id`: 
        - for a group, use the `groupID` from  Step 3
        - for a person use `id` from Step 4
    - set `slug`:
        - come up with a one-word or hyphenated keyword (`slug`) for this person or group 
        - the slug must match the frontmatter `slug` field value in the person's `person.md` profile so that messages can be correlated to the specific person in your notes
        - Example: `spongebob`
    - set `description` to `name` either the name from `conversations.csv` or something else e.g. "They get hooked!"
     
4. Repeat Steps 3 to 5 for every row

## Using signal_sqlite_md

Once you have the two CSV export files and you your `people.json` and `groups.json` configured, you're finally ready to run this tool.

The [command line options](https://github.com/thephm/message_md#command-line-options) are described in the [message_md](https://github.com/thephm/message_md) repo.

Example:

```
# python3 signal_sqlite_md.py -c ../../dev-output/config -s ../../signal_sqlite/ -f messages_2023-12-25_21-36.csv -d -o ../../dev-output -m spongebob -b 2023-12-20
```

where: 

- `c`onfig settings are in `../../dev-output/config`
- `s`ource folder is `../../signal_sqlite`
- `f`ile of CSV messages is `messages_2023-12-25_21-36.csv` in the `s`ource folder
- `o`utput the Markdown files to `../../dev-output`
- `m`y slug is `spongebob`
- `b`egin the export from `2023-12-20`

## Other info

In the `messages.csv` file, the attachments are referenced in this part of the message 

```
""path"":""0b\\0b82ab19cb4cab30f5041f7705aa890833cab2c32d662c2792814e0268c90e6c""
```
