import discord, re
from redbot.core import commands
from redbot.core import Config
from redbot.core import checks
from redbot.core.data_manager import cog_data_path
from typing import Optional, Union
from random import randint

class WordStats(commands.Cog):
	"""Tracks commonly used words."""
	def __init__(self, bot):
		self.bot = bot
		self.config = Config.get_conf(self, identifier=7345167905)
		self.config.register_guild(
			worddict = {},
			enableGuild = True,
			disabledChannels = []
		)
		self.config.register_member(
			worddict = {}
		)
	
	@commands.guild_only()
	@commands.command()
	async def wordstats(self, ctx, member: Optional[discord.Member]=None, amount: Optional[Union[int, str]]=30):
		"""
		Prints the most commonly used words.
		
		Use the optional paramater "member" to see the stats of a member.
		Use the optional paramater "amount" to change the number of words that are displayed, or to check the stats of a specific word.
		"""
		if member == None:
			mention = 'the server'
			worddict = await self.config.guild(ctx.guild).worddict()
		else:
			mention = member.display_name
			worddict = await self.config.member(member).worddict()
		order = list(reversed(sorted(worddict, key=lambda w: worddict[w])))
		if isinstance(amount, str):
			try:
				ordinal = lambda n: "%d%s" % (n,"tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])
				return await ctx.send(f'The word **{amount}** has been said by {mention} **{str(worddict[amount.lower()])}** times.\nIt is the **{ordinal(order.index(amount.lower())+1)}** most common word {mention} has said.')
			except KeyError:
				return await ctx.send(f'The word "{amount}" has not been said by {mention} yet.')
		result = ''
		smallresult = ''
		n = 0
		num = 0
		for word in order:
			if n < amount:
				smallresult += str(worddict[word])+' '+str(word)+'\n'
				n += 1
			result += str(worddict[word])+' '+str(word)+'\n'
			num += int(worddict[word])
		if smallresult == '':
			if mention == 'the server':
				mention = 'The server'
			await ctx.send(f'{mention} has not said any words yet.')
		else:
			await ctx.send(f'Out of {num} words and {len(worddict)} unique words, the {n} most common words that {mention} has said are:\n```{smallresult.rstrip()}```')

	@commands.guild_only()
	@checks.guildowner()
	@commands.group()
	async def wordstatsset(self, ctx):
		"""Config options for wordstats."""
		pass
			
	@commands.guild_only()
	@checks.guildowner()
	@wordstatsset.command()
	async def server(self, ctx, value: bool=None):
		"""
		Set if wordstats should record stats for this server.
		
		Defaults to True.
		This value is server specific.
		"""
		if value == None:
			v = await self.config.guild(ctx.guild).enableGuild()
			if v:
				await ctx.send('Stats are being recorded in this server.')
			else:
				await ctx.send('Stats are not being recorded in this server.')
		else:
			await self.config.guild(ctx.guild).enableGuild.set(value)
			if value:
				await ctx.send('Stats will now be recorded in this server.')
			else:
				await ctx.send('Stats will no longer be recorded in this server.')
				
	@commands.guild_only()
	@checks.guildowner()
	@wordstatsset.command()
	async def channel(self, ctx, value: bool=None):
		"""
		Set if wordstats should record stats for this channel.
		
		Defaults to True.
		This value is channel specific.
		"""
		if value == None:
			v = await self.config.guild(ctx.guild).disabledChannels()
			if ctx.channel.id not in v:
				await ctx.send('Stats are being recorded in this channel.')
			else:
				await ctx.send('Stats are not being recorded in this channel.')
		else:
			v = await self.config.guild(ctx.guild).disabledChannels()
			if value:
				if ctx.channel.id not in v:
					await ctx.send('Stats are already being recorded in this channel.')
				else:
					v.remove(ctx.channel.id)
					await self.config.guild(ctx.guild).disabledChannels.set(v)
					await ctx.send('Stats will now be recorded in this channel.')
			else:
				if ctx.channel.id in v:
					await ctx.send('Stats are already not being recorded in this channel.')
				else:
					v.append(ctx.channel.id)
					await self.config.guild(ctx.guild).disabledChannels.set(v)
					await ctx.send('Stats will no longer be recorded in this channel.')
			
	async def on_message(self, msg):
		"""Passively records all message contents."""
		if not msg.author.bot and isinstance(msg.channel, discord.TextChannel):
			enableGuild = await self.config.guild(msg.guild).enableGuild()
			disabledChannels = await self.config.guild(msg.guild).disabledChannels()
			if enableGuild and not msg.channel.id in disabledChannels:
				p = await self.bot.get_prefix(msg)
				if True in [msg.content.startswith(x) for x in p]:
					return
				words = str(re.sub(r'[^a-zA-Z ]', '', msg.content.lower())).split(' ')
				guilddict = await self.config.guild(msg.guild).worddict()
				memdict = await self.config.member(msg.author).worddict()
				for word in words:
					if not word:
						continue
					try:
						guilddict[word] += 1
					except KeyError:
						guilddict[word] = 1
					try:
						memdict[word] += 1
					except KeyError:
						memdict[word] = 1
				await self.config.guild(msg.guild).worddict.set(guilddict)
				await self.config.member(msg.author).worddict.set(memdict)
