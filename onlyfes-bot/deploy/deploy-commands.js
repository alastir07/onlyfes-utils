const { REST, Routes } = require('discord.js');
const { clientId, testGuildId, token } = require('../config.json');
const fs = require('node:fs');
const path = require('node:path');

const commands = [];
const testCommands = [];

// Grab all the command folders from the commands directory you created earlier
const foldersPath = path.join(__dirname, '..', 'commands');
const commandFolders = fs.readdirSync(foldersPath);

for (const folder of commandFolders) {
	// Grab all the command files from the commands directory you created earlier
	const commandsPath = path.join(foldersPath, folder);
	const commandFiles = fs.readdirSync(commandsPath).filter(file => file.endsWith('.js'));
	// Grab the SlashCommandBuilder#toJSON() output of each command's data for deployment
	for (const file of commandFiles) {
		const filePath = path.join(commandsPath, file);
		const command = require(filePath);
		if ('data' in command && 'execute' in command) {
            if (command.test) {
                testCommands.push(command.data.toJSON());
            } else {
                commands.push(command.data.toJSON());
            }
		} else {
			console.log(`[WARNING] The command at ${filePath} is missing a required "data" or "execute" property.`);
		}
	}
}

// Construct and prepare an instance of the REST module
const rest = new REST().setToken(token);

// and deploy your commands!
(async () => {
	try {
		console.log(`Started refreshing ${commands.length} application (/) commands.`);

		// The put method is used to fully refresh all commands in the guild with the current set
		const testCommandData = await rest.put(
			Routes.applicationGuildCommands(clientId, testGuildId),
			{ body: testCommands }
		);

        const commandData = await rest.put(
            Routes.applicationCommands(clientId),
            { body: commands }
        )

		console.log(`Successfully reloaded ${testCommandData.length} in-development application (/) commands.`);
        console.log(`Succesfully reloaded ${commandData.length} application (/) commands.`)
	} catch (error) {
		// And of course, make sure you catch and log any errors!
		console.error(error);
	}
})();