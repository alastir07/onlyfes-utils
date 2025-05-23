const { SlashCommandBuilder, userMention } = require('discord.js');

module.exports = {
	data: new SlashCommandBuilder()
		.setName('hello')
		.setDescription('Says hello to a user')
        .addUserOption(option =>
            option
                .setName('target')
                .setDescription('The user to say hello to')
                .setRequired(false)),

	async execute(interaction) {
        const target = interaction.options.getUser('target');
		await interaction.reply(`Hello ${ target ? userMention(target.id) : " World" }!`);
	},
    test: true
}