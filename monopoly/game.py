import discord
from redbot.core.data_manager import bundled_data_path
from redbot.core.utils.chat_formatting import pagify
from .constants import TILENAME, PRICEBUY, RENTPRICE, RRPRICE, CCNAME, CHANCENAME, MORTGAGEPRICE, TENMORTGAGEPRICE, HOUSEPRICE, PROPGROUPS
from .ai import MonopolyAI
import asyncio
import logging
import os
from io import BytesIO
from PIL import Image, ImageDraw
from random import randint, shuffle


class GetMemberError(Exception):
	"""Error thrown when a member cannot be found by MonopolyGame.get_member."""
	pass

class MonopolyGame():
	"""
	A game of Monopoly.
	If data is not provided, startCash and uid must be instead.
	
	Params:
	ctx = redbot.core.commands.context.Context, The context that should be used, used to send messages.
	cog = monopoly.monopoly.Monopoly, The cog the game is running on, used to stop the game.
	
	Kwargs:
	startCash = Optional[int], The amount of money players should start with.
	uid = Optional[list], The user IDs of the players of the game.
	data = Optional[dict], the save data to load from.
	"""
	def __init__(self, ctx, cog, *, startCash=None, uid=None, data=None):
		self.ctx = ctx
		self.bot = ctx.bot
		self.cog = cog
		if data is None:
			if startCash is None or not uid:
				raise ValueError('Either data or both startCash and uid must be provided.')
			self.p = 0
			self.uid = uid
			self.num = len(uid)
			self.numalive = self.num
			self.injail = [False] * self.num
			self.tile = [0] * self.num
			self.bal = [startCash] * self.num
			self.goojf = [0] * self.num #Get out of jail free (cards)
			self.isalive = [True] * self.num
			self.jailturn = [-1] * self.num
			self.ownedby = [
				-2, -1, -2, -1, -2,
				-1, -1, -2, -1, -1,
				-2, -1, -1, -1, -1,
				-1, -1, -2, -1, -1,
				-2, -1, -2, -1, -1,
				-1, -1, -1, -1, -1,
				-2, -1, -1, -2, -1,
				-1, -2, -1, -2, -1
			]
			self.numhouse = [
				-1, 0, -1, 0, -1,
				-1, 0, -1, 0, 0,
				-1, 0, -1, 0, 0,
				-1, 0, -1, 0, 0,
				-1, 0, -1, 0, 0,
				-1, 0, 0, -1, 0,
				-1, 0, 0, -1, 0,
				-1, -1, 0, -1, 0
			]
			self.ismortgaged = [
				-1, 0, -1, 0, -1,
				0, 0, -1, 0, 0,
				-1, 0, 0, 0, 0,
				0, 0, -1, 0, 0,
				-1, 0, -1, 0, 0,
				0, 0, 0, 0, 0,
				-1, 0, 0, -1, 0,
				0, -1, 0, -1, 0
			]
			self.freeparkingsum = 0
		else:
			self.p = data['p']
			self.injail = data['injail']
			self.tile = data['tile']
			self.bal = data['bal']
			self.goojf = data['goojf']
			self.isalive = data['isalive']
			self.jailturn = data['jailturn']
			self.ownedby = data['ownedby']
			self.numhouse = data['numhouse']
			self.ismortgaged = data['ismortgaged']
			self.num = data['num']
			self.numalive = data['numalive']
			self.uid = [
				u if isinstance(u, int)
				else MonopolyAI.from_save(u)
				for u in data['uid']
			]
			self.freeparkingsum = data['freeparkingsum']
		self.ccn = 0
		self.ccorder = list(range(17))
		shuffle(self.ccorder)
		self.chancen = 0
		self.chanceorder = list(range(16))
		shuffle(self.chanceorder)
		self.imgcache = {
			'ownedby': {'value': None, 'image': None},
			'ismortgaged': {'value': None, 'image': None},
			'tile': {'value': None, 'image': None},
			'numhouse': {'value': None, 'image': None}
		}
		self.is_ai = lambda p: isinstance(self.uid[p], MonopolyAI)
		self.log = logging.getLogger('red.flamecogs.monopoly')
		self.msg = ''
		self._task = asyncio.create_task(self.run())
		self._task.add_done_callback(self.error_callback) #Thanks Sinbad <3
	
	async def send_error(self):
		"""Sends a message to the channel after an error."""
		savename = str(self.ctx.message.id)
		await self.ctx.send(
			'A fatal error has occurred, shutting down.\n'
			'Please have the bot owner copy the error from console '
			'and post it in the support channel of <https://discord.gg/bYqCjvu>.\n'
			f'Your game was saved to `{savename}`.\n'
			f'You can load your save with `{self.ctx.prefix}monopoly {savename}`.'
		)
		async with self.cog.config.guild(self.ctx.guild).saves() as saves:
			saves[savename] = self.autosave
	
	async def send_timeout(self):
		"""Cleanup code when a user times out."""
		savename = str(self.ctx.message.id)
		await self.ctx.send(
			'You did not respond in time.\n'
			f'Your game was saved to `{savename}`.\n'
			f'You can load your save with `{self.ctx.prefix}monopoly {savename}`.'
		)
		async with self.cog.config.guild(self.ctx.guild).saves() as saves:
			saves[savename] = self.autosave
	
	def error_callback(self, fut):
		"""Checks for errors in stopped games."""
		try:
			fut.result()
		except (asyncio.CancelledError, GetMemberError):
			pass
		except asyncio.TimeoutError:
			asyncio.create_task(self.send_timeout())
		except Exception as exc:
			asyncio.create_task(self.send_error())
			msg = 'Error in Monopoly.\n'
			self.log.exception(msg)
			self.bot.dispatch('flamecogs_game_error', self, exc)
		try:
			self.cog.games.remove(self)
		except ValueError:
			pass
	
	def make_save(self):
		"""Creates a save dict from the current game state."""
		save = {}
		save['p'] = self.p
		save['injail'] = self.injail.copy()
		save['tile'] = self.tile.copy()
		save['bal'] = self.bal.copy()
		save['goojf'] = self.goojf.copy()
		save['isalive'] = self.isalive.copy()
		save['jailturn'] = self.jailturn.copy()
		save['ownedby'] = self.ownedby.copy()
		save['numhouse'] = self.numhouse.copy()
		save['ismortgaged'] = self.ismortgaged.copy()
		save['num'] = self.num
		save['numalive'] = self.numalive
		save['uid'] = [u if isinstance(u, int) else u.to_save() for u in self.uid]
		save['freeparkingsum'] = self.freeparkingsum
		self.autosave = save
	
	async def get_member(self, uid):
		"""Wrapper for guild.get_member that checks if the member is None."""
		if not isinstance(uid, int):
			return uid
		mem = self.ctx.guild.get_member(uid)
		if mem is None:
			savename = str(self.ctx.message.id)
			user = self.bot.get_user(uid)
			if user:
				msg = f'Player "{user}" (`{user.id}`)'
			else:
				msg = f'A player with the user ID `{uid}`'
			await self.ctx.send(
				f'{msg} in the current game is no longer in this guild.\n'
				f'Your game was saved to `{savename}`.\n'
				f'You can load your save with `{self.ctx.prefix}monopoly {savename}`.'
			)
			async with self.cog.config.guild(self.ctx.guild).saves() as saves:
				saves[savename] = self.autosave
			raise GetMemberError
		return mem
	
	async def send(self, *, img=False):
		"""Safely send the contents of self.msg."""
		if img:
			await self.ctx.send(file=discord.File(self.bprint()))
		for page in pagify(self.msg):
			await self.ctx.send(page)
		self.msg = ''
	
	async def run(self):
		"""Runs a game of monopoly."""
		while self.numalive > 1:
			self.make_save()
			if self.p >= self.num:
				self.p = 0
			#Skip dead players
			if not self.isalive[self.p]:
				self.p += 1
				continue
			self.num_doubles = 0
			self.was_doubles = True
			doMention = await self.cog.config.guild(self.ctx.guild).doMention()
			mem = await self.get_member(self.uid[self.p])
			if doMention:
				mention = mem.mention
			else:
				mention = mem.display_name
			self.msg += f'{mention}\'s turn!\n'
			#If they are in debt, handle that first
			if self.bal[self.p] < 0:
				await self.debt()
			#If they are in jail, that will be their turn
			if self.injail[self.p]:
				self.msg += 'You are in jail...\n'
				if self.jailturn[self.p] == -1:
					self.jailturn[self.p] = 0
				self.jailturn[self.p] += 1
				maxJailRolls = await self.cog.config.guild(self.ctx.guild).maxJailRolls()
				bailValue = await self.cog.config.guild(self.ctx.guild).bailValue()
				if self.jailturn[self.p] > maxJailRolls:
					self.msg += (
						f'Your {maxJailRolls} turn{"" if maxJailRolls == 1 else "s"} '
						f'in jail {"is" if maxJailRolls == 1 else "are"} up. \n'
					)
					if self.goojf[self.p] > 0:
						self.msg += (
							f'`b`: Post bail (${bailValue})'
							'\n`g`: Use a "Get Out of Jail Free" card '
							f'({self.goojf[self.p]} remaining)\n'
						)
					else:
						self.msg += f'You have to post bail (${bailValue}).\n'
				else:
					self.msg += f'`r`: Roll\n`b`: Post bail (${bailValue})\n'
					if self.goojf[self.p] > 0:
						self.msg += (
							'`g`: Use a "Get Out of Jail Free" '
							f'card ({self.goojf[self.p]} remaining)\n'
						)
				if self.jailturn[self.p] > maxJailRolls and self.goojf[self.p] == 0:
					choice = 'b'
				elif self.is_ai(self.p):
					choices = ['b']
					if self.jailturn[self.p] <= maxJailRolls:
						choices.append('r')
					if self.goojf[self.p] > 0:
						choices.append('g')
					config = await self.cog.config.guild(self.ctx.guild).all()
					choice = self.uid[self.p].jail_turn(self, config, choices)
				else:
					await self.send(img=True)
					choice = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in ('r', 'b', 'g')
						)
					)
					choice = choice.content.lower()
				if choice == 'r':
					if self.jailturn[self.p] > maxJailRolls:
						continue
					d1 = randint(1, 6)
					d2 = randint(1, 6)
					self.msg += f'You rolled a **{d1}** and a **{d2}**.\n'
					if d1 == d2:
						self.num_doubles += 1
						self.jailturn[self.p] = -1
						self.injail[self.p] = False
						self.msg += 'You rolled out of jail!\n'
						await self.land(d1 + d2)
					else:
						self.was_doubles = False
						self.msg += 'Sorry, not doubles.\n'
				elif choice == 'b':
					if self.bal[self.p] < bailValue and not (
						self.jailturn[self.p] > maxJailRolls
						and self.goojf[self.p] == 0
					):
						if not self.is_ai(self.p):
							await self.ctx.send(
								'Posting bail will put you in to debt. '
								'Are you sure you want to do that?'
							)
							choice = await self.bot.wait_for(
								'message',
								timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
								check=lambda m: (
									m.author.id == self.uid[self.p]
									and m.channel == self.ctx.channel
									and m.content.lower() in ('y', 'yes', 'n', 'no')
								)
							)
							choice = choice.content[0].lower()
							if choice == 'n':
								continue
					self.bal[self.p] -= bailValue 
					self.freeparkingsum += bailValue
					self.jailturn[self.p] = -1
					self.injail[self.p] = False
					self.msg += f'You paid ${bailValue} in bail. You now have ${self.bal[self.p]}.\n'
					if self.bal[self.p] < 0:
						await self.debt()
					if self.isalive[self.p]:
						d1 = randint(1, 6)
						d2 = randint(1, 6)
						self.msg += f'You rolled a **{d1}** and a **{d2}**.\n'
						if d1 == d2:
							self.num_doubles += 1
						else:
							self.was_doubles = False
						await self.land(d1 + d2)
				elif choice == 'g' and self.goojf[self.p] > 0:
					self.goojf[self.p] -= 1
					self.jailturn[self.p] = -1
					self.injail[self.p] = False
					d1 = randint(1, 6)
					d2 = randint(1, 6)
					self.msg += (
						'You used a "Get Out of Jail Free" card '
						f'({self.goojf[self.p]} remaining).\n'
						f'You rolled a **{d1}** and a **{d2}**.\n'
					)
					if d1 == d2:
						self.num_doubles += 1
					else:
						self.was_doubles = False
					await self.land(d1 + d2)
			#If not in jail, start a normal turn
			else:
				while self.was_doubles and self.isalive[self.p]:
					self.msg += '`r`: Roll\n`t`: Trade\n`h`: Manage houses\n`m`: Mortgage properties\n'
					if self.num_doubles == 0:
						self.msg += '`s`: Save\n'
					if self.is_ai(self.p):
						config = await self.cog.config.guild(self.ctx.guild).all()
						choice = self.uid[self.p].turn(self, config, ('r', 't', 'h', 'm'))
					else:
						await self.send(img=True)
						choice = await self.bot.wait_for(
							'message',
							timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
							check=lambda m: (
								m.author.id == self.uid[self.p]
								and m.channel == self.ctx.channel
								and m.content.lower() in ('r', 't', 'h', 'm', 's')
							)
						)
						choice = choice.content.lower()
					if choice == 'r':
						d1 = randint(1, 6)
						d2 = randint(1, 6)
						self.msg += f'You rolled a **{d1}** and a **{d2}**.\n'
						if d1 == d2:
							self.num_doubles += 1
						else:
							self.was_doubles = False
						if self.num_doubles == 3:
							self.tile[self.p] = 10
							self.injail[self.p] = True
							self.was_doubles = False
							self.msg += 'You rolled doubles 3 times in a row, you are now in jail!\n'
						else:
							await self.land(d1 + d2)
					elif choice == 't':
						await self.trade()
					elif choice == 'h':
						await self.house()
					elif choice == 'm':
						await self.mortgage()
					elif choice == 's' and self.num_doubles == 0:
						await self.ctx.send('Save file name?')
						choice = await self.bot.wait_for(
							'message',
							timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
							check=lambda m: (
								m.author.id == self.uid[self.p]
								and m.channel == self.ctx.channel
							)
						)
						savename = choice.content.replace(' ', '')
						async with self.cog.config.guild(self.ctx.guild).saves() as saves:
							if savename in ('delete', 'list'):
								self.msg = 'You cannot name your save that.\n'
							elif savename in saves:
								await self.ctx.send(
									'There is already another save with that name. Override it?'
								)
								timeout = await self.cog.config.guild(self.ctx.guild).timeoutValue()
								choice = await self.bot.wait_for(
									'message',
									timeout=timeout,
									check=lambda m: (
										m.author.id == self.uid[self.p]
										and m.channel == self.ctx.channel
									)
								)
								if choice.content.lower() not in ('yes', 'y'):
									self.msg = 'Not overriding.\n'
								else:
									saves[savename] = self.autosave
									return await self.ctx.send(
										f'Your game was saved to `{savename}`.\n'
										'You can load your save with '
										f'`{self.ctx.prefix}monopoly {savename}`.'
									)
							else:
								saves[savename] = self.autosave
								return await self.ctx.send(
									f'Your game was saved to `{savename}`.\n'
									'You can load your save with '
									f'`{self.ctx.prefix}monopoly {savename}`.'
								)
			#After roll
			while self.isalive[self.p]:
				self.msg += '`t`: Trade\n`h`: Manage houses\n`m`: Mortgage properties\n`d`: Done\n'
				if self.is_ai(self.p):
					config = await self.cog.config.guild(self.ctx.guild).all()
					choice = self.uid[self.p].turn(self, config, ('t', 'h', 'm', 'd'))
				else:
					await self.send(img=True)
					choice = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in ('t', 'h', 'm', 'd')
						)
					)
					choice = choice.content.lower()
				if choice == 't':
					await self.trade()
				elif choice == 'h':
					await self.house()
				elif choice == 'm':
					await self.mortgage()
				elif choice == 'd':
					break
			if self.msg:
				await self.send(img=True)
			self.p += 1
		doMention = await self.cog.config.guild(self.ctx.guild).doMention()
		winp = self.isalive.index(True)
		mem = await self.get_member(self.uid[winp])
		if doMention:
			mention = mem.mention
		else:
			mention = mem.display_name
		await self.ctx.send(f'{mention} wins!')
	
	async def land(self, distance):
		"""Move players and handle the events that happen when they land."""
		self.tile[self.p] += distance
		if self.tile[self.p] >= 40: #past go
			self.tile[self.p] -= 40
			doDoubleGo = await self.cog.config.guild(self.ctx.guild).doDoubleGo()
			goValue = await self.cog.config.guild(self.ctx.guild).goValue()
			if self.tile[self.p] == 0 and doDoubleGo:
				add = goValue * 2
			else:
				add = goValue
			self.bal[self.p] += add
			self.msg += (
				f'You {"landed on" if self.tile[self.p] == 0 else "passed"} go, +${add}! '
				f'You now have ${self.bal[self.p]}.\n'
			)
		self.msg += f'You landed at {TILENAME[self.tile[self.p]]}.\n'
		if self.ownedby[self.tile[self.p]] == self.p: #player is owner
			self.msg += 'You own this property already.\n'
		elif self.ismortgaged[self.tile[self.p]] == 1: #mortgaged
			self.msg += 'It is currently mortgaged. No rent is due.\n'
		elif self.ownedby[self.tile[self.p]] == -2: #unownable
			if self.tile[self.p] == 0: #go
				pass #already handled when moving
			elif self.tile[self.p] == 10: #jail
				self.msg += 'Just visiting!\n'
			elif self.tile[self.p] == 20: #free parking
				freeParkingValue = await self.cog.config.guild(self.ctx.guild).freeParkingValue()
				if freeParkingValue is None: #no reward
					pass
				elif freeParkingValue == 'tax': #tax reward
					self.bal[self.p] += self.freeparkingsum
					self.msg += (
						f'You earned ${self.freeparkingsum}. You now have ${self.bal[self.p]}.\n'
					)
					self.freeparkingsum = 0
				else: #hard coded reward
					self.bal[self.p] += freeParkingValue
					self.msg += f'You earned ${freeParkingValue}. You now have ${self.bal[self.p]}.\n'
			elif self.tile[self.p] == 30: #go to jail
				self.injail[self.p] = True
				self.tile[self.p] = 10
				self.was_doubles = False
				self.msg += 'You are now in jail!\n'
			elif self.tile[self.p] in (2, 17, 33): #cc
				card = self.ccorder[self.ccn]
				self.msg += f'Your card reads:\n{CCNAME[card]}\n'
				if card == 0:
					self.tile[self.p] = 0
					doDoubleGo = await self.cog.config.guild(self.ctx.guild).doDoubleGo()
					goValue = await self.cog.config.guild(self.ctx.guild).goValue()
					if doDoubleGo:
						self.bal[self.p] += goValue * 2
					else:
						self.bal[self.p] += goValue
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 1:
					self.bal[self.p] += 200
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 2:
					self.bal[self.p] -= 50
					self.freeparkingsum += 50
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 3:
					self.bal[self.p] += 50
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 4:
					self.goojf[self.p] += 1
					if self.goojf[self.p] == 1:
						self.msg += 'You now have 1 get out of jail free card.\n'
					else:
						self.msg += f'You now have {self.goojf[self.p]} get out of jail free cards.\n'
				elif card == 5:
					self.tile[self.p] = 10
					self.injail[self.p] = True
					self.was_doubles = False
				elif card == 6:
					self.bal[self.p] += 50 * (self.numalive - 1)
					self.msg += f'You now have ${self.bal[self.p]}.\n'
					for i in range(self.num):
						if self.isalive[i] and not i == self.p:
							mem = await self.get_member(self.uid[i])
							self.bal[i] -= 50
							self.msg += f'{mem.display_name} now has ${self.bal[i]}.\n'
				elif card in (7, 10, 16):
					self.bal[self.p] += 100
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 8:
					self.bal[self.p] += 20
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card in (9, 15):
					self.bal[self.p] += 10
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 11:
					self.bal[self.p] -= 100
					self.freeparkingsum += 100
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 12:
					self.bal[self.p] -= 150
					self.freeparkingsum += 150
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 13:
					self.bal[self.p] += 25
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 14:
					pay = 0
					for i in range(40):
						if self.ownedby[i] == self.p:
							#no houses / cannot have houses
							if self.numhouse[i] == 0 or self.numhouse[i] == -1:
								continue
							#hotel
							if self.numhouse[i] == 5:
								pay += 115
							#1-4 houses
							else:
								pay += 40 * self.numhouse[i]
					self.bal[self.p] -= pay
					self.msg += f'You paid ${pay} in repairs. You now have ${self.bal[self.p]}.\n'
				self.ccn += 1
				if self.ccn > 16:
					shuffle(self.ccorder)
					self.ccn = 0
			elif self.tile[self.p] in (7, 22, 36): #chance
				card = self.chanceorder[self.chancen]
				self.msg += f'Your card reads:\n{CHANCENAME[card]}\n'
				if card == 0:
					self.tile[self.p] = 0
					doDoubleGo = await self.cog.config.guild(self.ctx.guild).doDoubleGo()
					goValue = await self.cog.config.guild(self.ctx.guild).goValue()
					if doDoubleGo:
						self.bal[self.p] += goValue * 2
					else:
						self.bal[self.p] += goValue
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 1:
					if self.tile[self.p] > 24:
						goValue = await self.cog.config.guild(self.ctx.guild).goValue()
						self.bal[self.p] += goValue
						self.msg += f'You passed go, you now have ${self.bal[self.p]}.\n'
					self.tile[self.p] = 24
					await self.land(0)
				elif card == 2:
					if self.tile[self.p] > 11:
						goValue = await self.cog.config.guild(self.ctx.guild).goValue()
						self.bal[self.p] += goValue
						self.msg += f'You passed go, you now have ${self.bal[self.p]}.\n'
					self.tile[self.p] = 11
					await self.land(0)
				elif card == 3:
					if self.tile[self.p] <= 12:
						self.tile[self.p] = 12
					elif 12 < self.tile[self.p] <= 28:
						self.tile[self.p] = 28
					else:
						goValue = await self.cog.config.guild(self.ctx.guild).goValue()
						self.bal[self.p] += goValue
						self.msg += f'You passed go, you now have ${self.bal[self.p]}.\n'
						self.tile[self.p] = 12
					#must pay 10x rent if owned
					if (
						self.ownedby[self.tile[self.p]] != self.p
						and self.ownedby[self.tile[self.p]] >= 0
						and self.ismortgaged[self.tile[self.p]] != 1
					):
						memown = await self.get_member(
							self.uid[self.ownedby[self.tile[self.p]]]
						)
						self.bal[self.p] -= distance * 10
						self.bal[self.ownedby[self.tile[self.p]]] += distance * 10
						self.msg += (
							f'You paid ${distance * 10} of rent to {memown.display_name}. '
							f'You now have ${self.bal[self.p]}. {memown.display_name} now has '
							f'${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
						)
					else:
						await self.land(0)
				elif card == 4:
					if self.tile[self.p] <= 5:
						self.tile[self.p] = 5
					elif self.tile[self.p] <= 15:
						self.tile[self.p] = 15
					elif self.tile[self.p] <= 25:
						self.tile[self.p] = 25
					elif self.tile[self.p] <= 35:
						self.tile[self.p] = 35
					else:
						goValue = await self.cog.config.guild(self.ctx.guild).goValue()
						self.bal[self.p] += goValue
						self.msg += f'You passed go, you now have ${self.bal[self.p]}.\n'
						self.tile[self.p] = 5
					#must pay 2x rent if owned
					if (
						self.ownedby[self.tile[self.p]] != self.p
						and self.ownedby[self.tile[self.p]] >= 0
						and self.ismortgaged[self.tile[self.p]] != 1
					):
						memown = await self.get_member(
							self.uid[self.ownedby[self.tile[self.p]]]
						)
						rrcount = 0
						if self.ownedby[5] == self.ownedby[self.tile[self.p]]:
							rrcount += 1
						if self.ownedby[15] == self.ownedby[self.tile[self.p]]:
							rrcount += 1
						if self.ownedby[25] == self.ownedby[self.tile[self.p]]:
							rrcount += 1
						if self.ownedby[35] == self.ownedby[self.tile[self.p]]:
							rrcount += 1
						self.bal[self.p] -= RRPRICE[rrcount] * 2
						self.bal[self.ownedby[self.tile[self.p]]] += RRPRICE[rrcount] * 2
						self.msg += (
							f'You paid ${RRPRICE[rrcount] * 2} of rent to {memown.display_name}. '
							f'You now have ${self.bal[self.p]}. {memown.display_name} now has '
							f'${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
						)
					else:
						await self.land(0)
				elif card == 5:
					self.bal[self.p] += 50
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 6:
					self.goojf[self.p] += 1
					if self.goojf[self.p] == 1:
						self.msg += 'You now have 1 get out of jail free card.\n'
					else:
						self.msg += f'You now have {self.goojf[self.p]} get out of jail free cards.\n'
				elif card == 7:
					self.tile[self.p] -= 3
					await self.land(0)
				elif card == 8:
					self.tile[self.p] = 10
					self.injail[self.p] = True
					self.was_doubles = False
				elif card == 9:
					pay = 0
					for i in range(40):
						if self.ownedby[i] == self.p:
							#no houses / cannot have houses
							if self.numhouse[i] == 0 or self.numhouse[i] == -1:
								continue
							#hotel
							if self.numhouse[i] == 5:
								pay += 100
							#1-4 houses
							else:
								pay += 25 * self.numhouse[i]
					self.bal[self.p] -= pay
					self.msg += f'You paid ${pay} in repairs. You now have ${self.bal[self.p]}.\n'
				elif card == 10:
					self.bal[self.p] -= 15
					self.freeparkingsum += 15
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 11:
					if self.tile[self.p] > 5:
						goValue = await self.cog.config.guild(self.ctx.guild).goValue()
						self.bal[self.p] += goValue
						self.msg += f'You passed go, you now have ${self.bal[self.p]}.\n'
					self.tile[self.p] = 5
					await self.land(0)
				elif card == 12:
					self.tile[self.p] = 39
					await self.land(0)
				elif card == 13:
					self.bal[self.p] -= 50 * (self.numalive - 1)
					self.msg += f'You now have ${self.bal[self.p]}.\n'
					for i in range(self.num):
						if self.isalive[i] and not i == self.p:
							mem = await self.get_member(self.uid[i])
							self.bal[i] += 50
							self.msg += f'{mem.display_name} now has ${self.bal[i]}.\n'
				elif card == 14:
					self.bal[self.p] += 150
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				elif card == 15:
					self.bal[self.p] += 100
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				self.chancen += 1
				if self.chancen > 15:
					shuffle(self.chanceorder)
					self.chancen = 0
			elif self.tile[self.p] == 4: #income tax
				incomeValue = await self.cog.config.guild(self.ctx.guild).incomeValue()
				self.bal[self.p] -= incomeValue
				self.freeparkingsum += incomeValue
				self.msg += (
					f'You paid ${incomeValue} of Income Tax. You now have ${self.bal[self.p]}.\n'
				)
			elif self.tile[self.p] == 38: #luxury tax
				luxuryValue = await self.cog.config.guild(self.ctx.guild).luxuryValue()
				self.bal[self.p] -= luxuryValue
				self.freeparkingsum += luxuryValue
				self.msg += (
					f'You paid ${luxuryValue} of Luxury Tax. You now have ${self.bal[self.p]}.\n'
				)
		elif self.ownedby[self.tile[self.p]] == -1: #unowned and ownable
			if self.bal[self.p] >= PRICEBUY[self.tile[self.p]]: #can afford
				self.msg += (
					f'Would you like to buy {TILENAME[self.tile[self.p]]} '
					f'for ${PRICEBUY[self.tile[self.p]]}? (y/n) You have ${self.bal[self.p]}.\n'
				)
				if self.is_ai(self.p):
					config = await self.cog.config.guild(self.ctx.guild).all()
					choice = self.uid[self.p].buy_prop(self, config, self.tile[self.p])
				else:
					await self.send(img=True)
					choice = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in ('y', 'yes', 'n', 'no')
						)
					)
					choice = choice.content[0].lower()
				if choice == 'y': #buy property
					self.bal[self.p] -= PRICEBUY[self.tile[self.p]]
					self.ownedby[self.tile[self.p]] = self.p
					self.msg += (
						f'You now own {TILENAME[self.tile[self.p]]}!\n'
						f'You have ${self.bal[self.p]} remaining.\n'
					)
				else: #pass on property
					doAuction = await self.cog.config.guild(self.ctx.guild).doAuction()
					if doAuction:
						await self.auction()
			else: #cannot afford
				self.msg += (
					f'You cannot afford to buy {TILENAME[self.tile[self.p]]}, '
					f'you only have ${self.bal[self.p]} of ${PRICEBUY[self.tile[self.p]]}.\n'
				)
				doAuction = await self.cog.config.guild(self.ctx.guild).doAuction()
				if doAuction:
					await self.auction()
		elif RENTPRICE[self.tile[self.p]*6] == -1: #pay rr/util rent
			memown = await self.get_member(self.uid[self.ownedby[self.tile[self.p]]])
			if self.tile[self.p] in (12, 28): #utility
				if self.ownedby[12] == self.ownedby[28]: #own both
					self.bal[self.p] -= distance * 10
					self.bal[self.ownedby[self.tile[self.p]]] += distance * 10
					self.msg += (
						f'You paid ${distance * 10} of rent to {memown.display_name}. '
						f'You now have ${self.bal[self.p]}. {memown.display_name} now has '
						f'${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
					)
				else: #own only one
					self.bal[self.p] -= distance * 4
					self.bal[self.ownedby[self.tile[self.p]]] += distance * 4
					self.msg += (
						f'You paid ${distance * 4} of rent to {memown.display_name}. '
						f'You now have ${self.bal[self.p]}. {memown.display_name} now has '
						f'${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
					) 
			elif self.tile[self.p] in (5, 15, 25, 35): #railroad
				rrcount = 0
				if self.ownedby[5] == self.ownedby[self.tile[self.p]]:
					rrcount += 1
				if self.ownedby[15] == self.ownedby[self.tile[self.p]]:
					rrcount += 1
				if self.ownedby[25] == self.ownedby[self.tile[self.p]]:
					rrcount += 1
				if self.ownedby[35] == self.ownedby[self.tile[self.p]]:
					rrcount += 1
				self.bal[self.p] -= RRPRICE[rrcount]
				self.bal[self.ownedby[self.tile[self.p]]] += RRPRICE[rrcount]
				self.msg += (
					f'You paid ${RRPRICE[rrcount]} of rent to {memown.display_name}. '
					f'You now have ${self.bal[self.p]}. {memown.display_name} now has '
					f'${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
				)
		else: #pay normal rent
			memown = await self.get_member(self.uid[self.ownedby[self.tile[self.p]]])
			isMonopoly = False
			for group in PROPGROUPS:
				if self.tile[self.p] in group:
					if all(
						[self.ownedby[self.tile[self.p]] == self.ownedby[prop] for prop in group]
					):
						isMonopoly = True
					break
			if isMonopoly and self.numhouse[self.tile[self.p]] == 0: #2x rent
				rent = 2 * RENTPRICE[self.tile[self.p] * 6]
			else: #normal rent
				rent = RENTPRICE[(self.tile[self.p] * 6) + self.numhouse[self.tile[self.p]]]
			self.bal[self.p] -= rent
			self.bal[self.ownedby[self.tile[self.p]]] += rent
			self.msg += (
				f'You paid ${rent} of rent to {memown.display_name}. '
				f'You now have ${self.bal[self.p]}. '
				f'{memown.display_name} now has ${self.bal[self.ownedby[self.tile[self.p]]]}.\n'
			)
		if self.bal[self.p] < 0:
			await self.debt()

	async def auction(self):
		"""Hold auctions for unwanted properties."""
		minRaise = await self.cog.config.guild(self.ctx.guild).minRaise()
		self.msg += (
			f'{TILENAME[self.tile[self.p]]} is now up for auction!\n'
			'Anyone can bid by typing the value of their bid. '
			f'Bids must increase the price by ${minRaise}. '
			'After 15 seconds with no bids, the highest bid will win.'
		)
		await self.send(img=True)
		highest = None
		highp = None
		def auctioncheck(m):
			try:
				if highest is None:
					return (
						m.author.id in self.uid
						and self.bal[self.uid.index(m.author.id)] >= int(m.content)
						and self.isalive[self.uid.index(m.author.id)]
					)
				return (
					m.author.id in self.uid
					and self.bal[self.uid.index(m.author.id)] >= int(m.content)
					and self.isalive[self.uid.index(m.author.id)]
					and (highest + minRaise) <= int(m.content)
				)
			except Exception:
				return False
		while True:
			try:
				bid_msg = await self.bot.wait_for(
					'message',
					check=auctioncheck,
					timeout=15
				)
			except asyncio.TimeoutError:
				break
			highest = int(bid_msg.content)
			highp = self.uid.index(bid_msg.author.id)
			await self.ctx.send(
				f'{bid_msg.author.display_name} has the highest bid with ${highest}.'
			)
		if highp is None:
			self.msg = 'Nobody bid...\n'
		else:
			memwin = await self.get_member(self.uid[highp])
			self.bal[highp] -= highest
			self.ownedby[self.tile[self.p]] = highp
			self.msg = (
				f'{memwin.display_name} wins with a bid of ${highest}!\n'
				f'{memwin.display_name} now owns {TILENAME[self.tile[self.p]]} '
				f'and has ${self.bal[highp]}.\n'
			)
	
	async def debt(self):
		"""Handle players who have a negative balance."""
		while self.bal[self.p] < 0 and self.isalive[self.p]:
			self.msg += (
				f'You are in debt. You have ${self.bal[self.p]}.\n'
				'Select an option to get out of debt:\n'
				'`t`: Trade\n`h`: Manage houses\n`m`: Mortgage properties\n`g`: Give up\n'
			)
			if self.is_ai(self.p):
				config = await self.cog.config.guild(self.ctx.guild).all()
				choice = self.uid[self.p].turn(self, config, ('t', 'h', 'm', 'g'))
			else:
				await self.send(img=True)
				choice = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
						and m.content.lower() in ('t', 'h', 'm', 'g')
					)
				)
				choice = choice.content.lower()
			if choice == 't':
				await self.trade()
			elif choice == 'h':
				await self.house()
			elif choice == 'm':
				await self.mortgage()
			elif choice == 'g':
				if not self.is_ai(self.p):
					await self.ctx.send('Are you sure? (y/n)')
					choice = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in ('y', 'yes', 'n', 'no')
						)
					)
					choice = choice.content[0].lower()
					if choice == 'n':
						continue
				for i in range(40):
					if self.ownedby[i] == self.p:
						self.ownedby[i] = -1
						self.numhouse[i] = 0
						self.ismortgaged[i] = 0
				self.numalive -= 1
				self.isalive[self.p] = False
				self.injail[self.p] = False #prevent them from executing jail code
				mem = await self.get_member(self.uid[self.p])
				self.msg += f'{mem.display_name} is now out of the game.\n'
				return
		self.msg += f'You are now out of debt. You now have ${self.bal[self.p]}.\n'
	
	async def trade(self):
		"""Trade properties between players."""
		tradeable_p = []
		tradeable_partner = []
		money_p = 0
		money_partner = 0
		goojf_p = 0
		goojf_partner = 0
		colors = {
			1: 'Brown', 3: 'Brown',
			6: 'Light Blue', 8: 'Light Blue', 9: 'Light Blue',
			11: 'Pink', 13: 'Pink', 14: 'Pink',
			16: 'Orange', 18: 'Orange', 19: 'Orange',
			21: 'Red', 23: 'Red', 24: 'Red',
			26: 'Yellow', 27: 'Yellow', 29: 'Yellow',
			31: 'Green', 32: 'Green', 34: 'Green',
			37: 'Dark Blue', 39: 'Dark Blue',
			5: 'Railroad', 15: 'Railroad', 25: 'Railroad', 35: 'Railroad', 
			12: 'Utility', 28: 'Utility'
		}
		self.msg += '```\n'
		for a in range(self.num):
			if self.isalive[a] and a != self.p:
				mem = await self.get_member(self.uid[a])
				name = mem.display_name
				self.msg += f'{a} {name}\n'
		self.msg += '```Select the player you want to trade with.\n`c`: Cancel\n'
		await self.send(img=True)
		def tradecheck(m):
			if m.author.id == self.uid[self.p] and m.channel == self.ctx.channel:
				try:
					m = int(m.content)
				except Exception:
					if m.content.lower() == 'c':
						return True
					return False
				if 0 <= m < self.num and self.isalive[m] and m != self.p:
					return True
			return False
		choice = await self.bot.wait_for(
			'message',
			timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
			check=tradecheck
		)
		choice = choice.content.lower()
		if choice == 'c':
			return
		partner = int(choice)
		for a in range(40):
			#properties cannot be traded if any property in their color group has a house
			groupHasHouse = False
			for group in PROPGROUPS:
				if a in group:
					if any(self.numhouse[prop] not in (-1, 0) for prop in group):
						groupHasHouse = True
			if groupHasHouse:
				continue
			if self.ownedby[a] == self.p:
				tradeable_p.append(a)
			elif self.ownedby[a] == partner:
				tradeable_partner.append(a)
		to_trade_p = [False for _ in range(len(tradeable_p))]
		to_trade_partner = [False for _ in range(len(tradeable_partner))]
		while True:
			self.msg += '```\nid sel color      name\n'
			for a in range(len(tradeable_p)):
				if to_trade_p[a]:
					self.msg += '{:2}  +  {:10} {}\n'.format(
						a, colors[tradeable_p[a]], TILENAME[tradeable_p[a]]
					)
				else:
					self.msg += '{:2}     {:10} {}\n'.format(
						a, colors[tradeable_p[a]], TILENAME[tradeable_p[a]]
					)
			self.msg += '\n'
			if money_p != 0:
				self.msg += f'${money_p}\n'
			if goojf_p == 1:
				self.msg += '1 get out of jail free card.\n'
			elif goojf_p != 0:
				self.msg += f'{goojf_p} get out of jail free cards.\n'
			self.msg += (
				'```Type the ID of any property you want to toggle trading to them.\n'
				'`m`: Give money\n`j`: Give get out of jail free cards\n`d`: Done\n`c`: Cancel\n'
			)
			await self.send(img=True)
			valid = [str(x) for x in range(len(tradeable_p))] + ['m', 'j', 'd', 'c']
			choice = await self.bot.wait_for(
				'message',
				timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
				check=lambda m: (
					m.author.id == self.uid[self.p]
					and m.channel == self.ctx.channel
					and m.content.lower() in valid
				)
			)
			choice = choice.content.lower()
			if choice == 'm':
				await self.ctx.send(f'How much money? You have ${self.bal[self.p]}.')
				money = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
					)
				)
				try:
					money = int(money.content)
				except:
					self.msg += 'You need to specify a number.\n'
				else:
					if money > self.bal[self.p]:
						self.msg += 'You do not have that much money.\n'
					elif money < 0:
						self.msg += 'You cannot give a negative amount of money.\n'
					else:
						money_p = money
			elif choice == 'j':
				if self.goojf[self.p] == 0:
					self.msg += 'You do not have any get out of jail free cards to give.\n'
					continue
				await self.ctx.send(f'How many? You have {self.goojf[self.p]}.')
				cards = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
					)
				)
				try:
					cards = int(cards.content)
				except:
					self.msg += 'You need to specify a number.\n'
				else:
					if cards > self.goojf[self.p]:
						self.msg += 'You do not have that many get out of jail free cards.\n'
					elif cards < 0:
						self.msg += 'You cannot give a negative amount of get out of jail free cards.\n'
					else:
						goojf_p = cards
			elif choice == 'd':
				break
			elif choice == 'c':
				return
			else:
				choice = int(choice)
				to_trade_p[choice] = not to_trade_p[choice]
		while True:
			self.msg += '```\nid sel color      name\n'
			for a in range(len(tradeable_partner)):
				if to_trade_partner[a]:
					self.msg += '{:2}  +  {:10} {}\n'.format(
						a, colors[tradeable_partner[a]], TILENAME[tradeable_partner[a]]
					)
				else:
					self.msg += '{:2}     {:10} {}\n'.format(
						a, colors[tradeable_partner[a]], TILENAME[tradeable_partner[a]]
					)
			self.msg += '\n'
			if money_partner != 0:
				self.msg += f'${money_partner}\n'
			if goojf_partner == 1:
				self.msg += '1 get out of jail free card.\n'
			elif goojf_partner != 0:
				self.msg += f'{goojf_partner} get out of jail free cards.\n'
			self.msg += (
				'```Type the ID of any property you want '
				'to toggle requesting them to trade to you.\n'
				'`m`: Request money\n`j`: Request get out of jail free cards\n'
				'`d`: Done\n`c`: Cancel\n'
			)
			await self.send(img=True)
			valid = [str(x) for x in range(len(tradeable_partner))] + ['m', 'j', 'd', 'c']
			choice = await self.bot.wait_for(
				'message',
				timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
				check=lambda m: (
					m.author.id == self.uid[self.p]
					and m.channel == self.ctx.channel
					and m.content.lower() in valid
				)
			)
			choice = choice.content.lower()
			if choice == 'm':
				await self.ctx.send(f'How much money? They have ${self.bal[partner]}.')
				money = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
					)
				)
				try:
					money = int(money.content)
				except:
					self.msg += 'You need to specify a number.\n'
				else:
					if money > self.bal[partner]:
						self.msg += 'They do not have that much money.\n'
					elif money < 0:
						self.msg += 'You cannot take a negative amount of money.\n'
					else:
						money_partner = money
			elif choice == 'j':
				if self.goojf[partner] == 0:
					self.msg += 'They do not have any get out of jail free cards to give.\n'
					continue
				await self.ctx.send(f'How many? They have {self.goojf[partner]}.')
				cards = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
					)
				)
				try:
					cards = int(cards.content)
				except:
					self.msg += 'You need to specify a number.\n'
				else:
					if cards > self.goojf[partner]:
						self.msg += 'They do not have that many get out of jail free cards.\n'
					elif cards < 0:
						self.msg += 'You cannot take a negative amount of get out of jail free cards.\n'
					else:
						goojf_partner = cards
			elif choice == 'd':
				break
			elif choice == 'c':
				return
			else:
				choice = int(choice)
				to_trade_partner[choice] = not to_trade_partner[choice]
		hold_p = ''
		hold_partner = ''
		for a in range(len(tradeable_p)):
			if to_trade_p[a]:
				hold_p += '{:10} {}\n'.format(
					colors[tradeable_p[a]], TILENAME[tradeable_p[a]]
				)
		hold_p += '\n'
		if money_p != 0:
			hold_p += f'${money_p}\n'
		if goojf_p == 1:
			hold_p += '1 get out of jail free card.\n'
		elif goojf_p != 0:
			hold_p += f'{goojf_p} get out of jail free cards.\n'
		for a in range(len(tradeable_partner)):
			if to_trade_partner[a]:
				hold_partner += '{:10} {}\n'.format(
					colors[tradeable_partner[a]], TILENAME[tradeable_partner[a]]
				)
		hold_partner += '\n'
		if money_partner != 0:
			hold_partner += f'${money_partner}\n'
		if goojf_partner == 1:
			hold_partner += '1 get out of jail free card.\n'
		elif goojf_partner != 0:
			hold_partner += f'{goojf_partner} get out of jail free cards.\n'
		if not hold_p.strip():
			hold_p = 'Nothing :('
		if not hold_partner.strip():
			hold_partner = 'Nothing :('
		self.msg += (
			f'You will give:\n```\n{hold_p}```\nYou will get:\n```\n{hold_partner}```\n'
			'`a`: Accept\n`c`: Cancel\n'
		)
		await self.send(img=True)
		choice = await self.bot.wait_for(
			'message',
			timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
			check=lambda m: (
				m.author.id == self.uid[self.p]
				and m.channel == self.ctx.channel
				and m.content.lower() in ('a', 'c')
			)
		)
		choice = choice.content.lower()
		if choice == 'c':
			return
		doMention = await self.cog.config.guild(self.ctx.guild).doMention()
		member_p = await self.get_member(self.uid[self.p])
		member_partner = await self.get_member(self.uid[partner])
		if doMention:
			mention = member_partner.mention
		else:
			mention = member_partner.display_name
		self.msg += (
			f'{mention}, {member_p.display_name} would like to trade with you. '
			f'Here is their offer.\n\nYou will give:\n```\n{hold_partner}```\n'
			f'You will get:\n```\n{hold_p}```\nDo you accept (y/n)?\n'
		)
		if self.is_ai(partner):
			temp_p = [x for idx, x in enumerate(tradeable_p) if to_trade_p[idx]]
			temp_partner = [x for idx, x in enumerate(tradeable_partner) if to_trade_partner[idx]]
			choice = member_partner.incoming_trade(
				self,
				self.p,
				[money_p, goojf_p, temp_p],
				[money_partner, goojf_partner, temp_partner]
			)
		else:
			await self.send(img=True)
			choice = await self.bot.wait_for(
				'message',
				timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
				check=lambda m: (
					m.author.id == self.uid[partner]
					and m.channel == self.ctx.channel
					and m.content.lower() in ('y', 'yes', 'n', 'no')
				)
			)
			choice = choice.content[0].lower()
		if choice == 'n':
			return
		self.bal[self.p] += money_partner
		self.bal[partner] += money_p
		self.bal[self.p] -= money_p
		self.bal[partner] -= money_partner
		self.goojf[self.p] += goojf_partner
		self.goojf[partner] += goojf_p
		self.goojf[self.p] -= goojf_p
		self.goojf[partner] -= goojf_partner
		for a in range(len(tradeable_p)):
			if to_trade_p[a]:
				self.ownedby[tradeable_p[a]] = partner
		for a in range(len(tradeable_partner)):
			if to_trade_partner[a]:
				self.ownedby[tradeable_partner[a]] = self.p
	
	async def house(self):
		"""Buy and sell houses on monopolies."""
		colors = {
			'Brown': [1, 3], 'Light Blue': [6, 8, 9],
			'Pink': [11, 13, 14], 'Orange': [16, 18, 19],
			'Red': [21, 23, 24], 'Yellow': [26, 27, 29],
			'Green': [31, 32, 34], 'Dark Blue': [37, 39]
		}
		houseable = []
		for color in colors:
			#all owned by the current player
			if not all(self.ownedby[prop] == self.p for prop in colors[color]):
				continue
			#no props are mortgaged
			if any(self.ismortgaged[prop] for prop in colors[color]):
				continue
			houseable.append(color)
		if not houseable:
			self.msg += 'You do not have any properties that are eligible for houses.\n'
			return
		while True:
			self.msg += '```\nid price color\n'
			i = 0
			for color in houseable:
				self.msg += '{:2} {:5d} {}\n'.format(i, HOUSEPRICE[colors[color][0]], color)
				i += 1
			self.msg += (
				'```Type the ID of the color group you want to manage.\n'
				f'You have ${self.bal[self.p]}\n`d`: Done\n'
			)
			if self.is_ai(self.p):
				choice = self.uid[self.p].grab_from_cache()
			else:
				await self.send(img=True)
				choice = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
						and m.content.lower() in [str(x) for x in range(len(houseable))] + ['d']
					)
				)
				choice = choice.content.lower()
			if choice == 'd':
				break
			choice = int(choice)
			props = colors[houseable[choice]]
			#start off with the current values
			new_values = []
			for a in props:
				new_values.append(self.numhouse[a])
			while True:
				self.msg += '```\nid numh name\n'
				i = 0
				for a in props:
					self.msg += '{:2} {:4} {}\n'.format(i, new_values[i], TILENAME[a])
					i += 1
				self.msg += (
					'```Type the ID of the property you want to change.\n'
					'`c`: Confirm\n`e`: Exit without changing\n'
				)
				if self.is_ai(self.p):
					choice = self.uid[self.p].grab_from_cache()
				else:
					await self.send(img=True)
					choice = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in [str(x) for x in range(len(props))] + ['c', 'e']
						)
					)
					choice = choice.content.lower()
				if choice == 'e':
					break
				if choice == 'c':
					if max(new_values) - min(new_values) > 1:
						self.msg += 'That is not a valid house setup.\n'
						continue
					test = self.numhouse[:] 
					for a in range(len(new_values)):
						test[props[a]] = new_values[a]
					houseLimit = await self.cog.config.guild(self.ctx.guild).houseLimit()
					total_houses = sum(x for x in test if x in (1, 2, 3, 4))
					if total_houses > houseLimit and houseLimit != -1:
						self.msg += (
							'There are not enough houses for that setup.'
							f'\nMax houses: `{houseLimit}`\nRequired houses: `{total_houses}`\n'
						)
						continue
					hotelLimit = await self.cog.config.guild(self.ctx.guild).hotelLimit()
					total_hotels = sum(1 for x in test if x == 5)
					if total_hotels > hotelLimit and hotelLimit != -1:
						self.msg += (
							'There are not enough hotels for that setup.'
							f'\nMax hotels: `{hotelLimit}`\nRequired houses: `{total_hotels}`\n'
						)
						continue 
					change = 0
					for a in range(len(new_values)):
						change += new_values[a] - self.numhouse[props[a]]
					if change == 0:
						self.msg += 'No houses were changed.\n'
						break
					price = abs(change) * HOUSEPRICE[props[0]]
					if price > self.bal[self.p] and change > 0:
						self.msg += 'You cannot afford to buy that many houses.\n'
						continue
					if not self.is_ai(self.p):
						if abs(change) == 1:
							plural = ''
						else:
							plural = 's'
						if change > 0:
							await self.ctx.send(
								f'Are you sure you want to buy {change} house{plural}? (y/n) '
								f'It will cost ${price} at ${HOUSEPRICE[props[0]]} per house.'
							)
						else:
							await self.ctx.send(
								f'Are you sure you want to sell {abs(change)} house{plural}? (y/n) '
								f'You will get ${price // 2} at '
								f'${HOUSEPRICE[props[0]] // 2} per house.'
							)
						choice = await self.bot.wait_for(
							'message',
							timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
							check=lambda m: (
								m.author.id == self.uid[self.p]
								and m.channel == self.ctx.channel
								and m.content.lower() in ('y', 'yes', 'n', 'no')
							)
						)
						choice = choice.content[0].lower()
						if choice == 'n':
							continue
					for a in range(len(new_values)):
						self.numhouse[props[a]] = new_values[a]
					if change > 0:
						self.bal[self.p] -= price
					else:
						self.bal[self.p] += price // 2
					self.msg += f'You now have ${self.bal[self.p]}.\n'
					break
				else:
					choice = int(choice)
					self.msg += f'How many houses do you want on {TILENAME[props[choice]]}?\n`c`: Cancel\n'
					if self.is_ai(self.p):
						value = self.uid[self.p].grab_from_cache()
					else:
						await self.send()
						value = await self.bot.wait_for(
							'message',
							timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
							check=lambda m: (
								m.author.id == self.uid[self.p]
								and m.channel == self.ctx.channel
								and m.content.lower() in [str(x) for x in range(6)] + ['c']
							)
						)
						value = value.content.lower()
						if value == 'c':
							continue
					value = int(value)
					new_values[choice] = value
	
	async def mortgage(self):
		"""Mortgage and unmortgage properties."""
		mortgageable = []
		for a in range(40):
			if self.ownedby[a] == self.p and self.numhouse[a] <= 0:
				mortgageable.append(a)
		#properties cannot be mortgaged if any property in their color group has a house
		for a in mortgageable:
			groupHasHouse = False
			for group in PROPGROUPS:
				if a in group:
					if any(self.numhouse[prop] not in (-1, 0) for prop in group):
						groupHasHouse = True
					break
			if groupHasHouse:
				mortgageable.remove(a)
		if not mortgageable:
			self.msg += 'You do not have any properties that are able to be mortgaged.\n'
			return
		while True:
			self.msg += '```\nid isM price name\n'
			i = 0
			for a in mortgageable:
				if self.ismortgaged[a] == 1:
					self.msg += '{:2}   + {:5d} {}\n'.format(
						i, MORTGAGEPRICE[a], TILENAME[a]
					)
				else:
					self.msg += '{:2}     {:5d} {}\n'.format(
						i, MORTGAGEPRICE[a], TILENAME[a]
					)
				i += 1
			self.msg += '```Type the ID of the property you want to mortgage or unmortgage.\n`d`: Done\n'
			if self.is_ai(self.p):
				choice = self.uid[self.p].grab_from_cache()
			else:
				await self.send(img=True)
				choice = await self.bot.wait_for(
					'message',
					timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
					check=lambda m: (
						m.author.id == self.uid[self.p]
						and m.channel == self.ctx.channel
						and m.content.lower() in [str(x) for x in range(len(mortgageable))] + ['d']
					)
				)
				choice = choice.content.lower()
			if choice == 'd':
				break
			choice = int(choice)
			if self.ismortgaged[mortgageable[choice]] == 0:
				if not self.is_ai(self.p):
					await self.ctx.send(
						f'Mortgage {TILENAME[mortgageable[choice]]} for '
						f'${MORTGAGEPRICE[mortgageable[choice]]}? (y/n) You have ${self.bal[self.p]}.'
					)
					yes_or_no = await self.bot.wait_for(
						'message',
						timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
						check=lambda m: (
							m.author.id == self.uid[self.p]
							and m.channel == self.ctx.channel
							and m.content.lower() in ('y', 'yes', 'n', 'no')
						)
					)
					yes_or_no = yes_or_no.content[0].lower()
					if yes_or_no == 'n':
						continue
				self.bal[self.p] += MORTGAGEPRICE[mortgageable[choice]]
				self.ismortgaged[mortgageable[choice]] = 1
				self.msg += f'You now have ${self.bal[self.p]}.\n'
			else:
				if self.bal[self.p] >= TENMORTGAGEPRICE[mortgageable[choice]]:
					if not self.is_ai(self.p):
						await self.ctx.send(
							f'Unmortgage {TILENAME[mortgageable[choice]]} for '
							f'${TENMORTGAGEPRICE[mortgageable[choice]]}? (y/n) '
							f'You have ${self.bal[self.p]}. '
							f'(${MORTGAGEPRICE[mortgageable[choice]]} + 10% interest)'
						)
						yes_or_no = await self.bot.wait_for(
							'message',
							timeout=await self.cog.config.guild(self.ctx.guild).timeoutValue(),
							check=lambda m: (
								m.author.id == self.uid[self.p]
								and m.channel == self.ctx.channel
								and m.content.lower() in ('y', 'yes', 'n', 'no')
							)
						)
						yes_or_no = yes_or_no.content[0].lower()
						if yes_or_no == 'n':
							continue
					self.bal[self.p] -= TENMORTGAGEPRICE[mortgageable[choice]]
					self.ismortgaged[mortgageable[choice]] = 0
					self.msg += f'You now have ${self.bal[self.p]}.\n'
				else:
					self.msg += (
						f'You cannot afford the ${TENMORTGAGEPRICE[mortgageable[choice]]} '
						f'it would take to unmortgage that. You only have ${self.bal[self.p]}.\n'
					)
	
	def bprint(self): 
		"""Creates an image of a monopoly board with the current game data."""
		pcolor = [
			(0, 0, 255, 255),
			(255, 0, 0, 255),
			(0, 255, 0, 255),
			(255, 255, 0, 255),
			(0, 255, 255, 255),
			(255, 140, 0, 255),
			(140, 0, 255, 255),
			(255, 0, 255, 255)
		]
		#OWNEDBY
		if self.imgcache['ownedby']['value'] != self.ownedby:
			self.imgcache['ownedby']['value'] = self.ownedby.copy()
			img = Image.new('RGBA', (750, 750), (0, 0, 0, 0))
			d = ImageDraw.Draw(img)
			for t in range(40):
				if self.ownedby[t] > -1:
					if 0 < t < 10:
						d.rectangle(
							[(650-(t*50))-39,702,(650-(t*50))-10,735],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[(650-(t*50))-37,702,(650-(t*50))-12,733],
							fill=pcolor[self.ownedby[t]]
						)
					elif 10 < t < 20:
						d.rectangle(
							[16,(650-((t-10)*50))-39,50,(650-((t-10)*50))-10],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[18,(650-((t-10)*50))-37,50,(650-((t-10)*50))-12],
							fill=pcolor[self.ownedby[t]]
						)
					elif 20 < t < 30:
						d.rectangle(
							[(100+((t-20)*50))+11,16,(100+((t-20)*50))+41,50],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[(100+((t-20)*50))+13,18,(100+((t-20)*50))+39,50],
							fill=pcolor[self.ownedby[t]]
						)
					elif 30 < t < 40:
						d.rectangle(
							[702,(100+((t-30)*50))+11,736,(100+((t-30)*50))+41],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[702,(100+((t-30)*50))+13,734,(100+((t-30)*50))+39],
							fill=pcolor[self.ownedby[t]]
						)
			self.imgcache['ownedby']['image'] = img
		#ISMORTGAGED
		if self.imgcache['ismortgaged']['value'] != self.ismortgaged:
			self.imgcache['ismortgaged']['value'] = self.ismortgaged.copy()
			img = Image.new('RGBA', (750, 750), (0, 0, 0, 0))
			m = Image.open(bundled_data_path(self.cog) / 'mortgage.png')
			for t in range(40):
				if self.ismortgaged[t] == 1:
					if 0 < t < 10:
						img.paste(m, box=(600-(t*50), 600), mask=m)
					elif 10 < t < 20:
						rotate = m.transpose(method=Image.ROTATE_270)
						img.paste(rotate, box=(52, 600-((t-10)*50)), mask=rotate)
					elif 20 < t < 30:
						rotate = m.transpose(method=Image.ROTATE_180)
						img.paste(rotate, box=(102+((t-20)*50), 52), mask=rotate)
					elif 30 < t < 40:
						rotate = m.transpose(method=Image.ROTATE_90)
						img.paste(rotate, box=(600, 102+((t-30)*50)), mask=rotate)
			self.imgcache['ismortgaged']['image'] = img
		#TILE
		#Because the player int used to be 1 indexed, the players would be in the wrong
		#position without 1 indexing and subtracting 1 from t when calling self.tile[t]
		#and pcolor[t]. I could fix this by changing the hard coded values, but this is
		#easier in the short term.
		if self.imgcache['tile']['value'] != self.tile:
			self.imgcache['tile']['value'] = self.tile.copy()
			img = Image.new('RGBA', (750, 750), (0, 0, 0, 0))
			d = ImageDraw.Draw(img)
			for t in range(1, self.num + 1):
				if not self.isalive[t-1]:
					continue
				if self.tile[t-1] == 0:
					d.rectangle(
						[(12*(t-1))+604,636,(12*(t-1))+614,646], fill=(0,0,0,255)
					)
					d.rectangle(
						[(12*(t-1))+605,637,(12*(t-1))+613,645], fill=pcolor[t-1]
					)
				elif 0 < self.tile[t-1] < 10:
					if t < 5:
						d.rectangle(
							[((650-(self.tile[t-1]*50))-47)+(12*(t-1)),636,((650-(self.tile[t-1]*50))-37)+(12*(t-1)),646],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[((650-(self.tile[t-1]*50))-46)+(12*(t-1)),637,((650-(self.tile[t-1]*50))-38)+(12*(t-1)),645],
							fill=pcolor[t-1]
						)
					else:
						d.rectangle(
							[((650-(self.tile[t-1]*50))-47)+(12*(t-5)),648,((650-(self.tile[t-1]*50))-37)+(12*(t-5)),658],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[((650-(self.tile[t-1]*50))-46)+(12*(t-5)),649,((650-(self.tile[t-1]*50))-38)+(12*(t-5)),657],
							fill=pcolor[t-1]
						)
				elif self.tile[t-1] == 10:
					d.rectangle(
						[106,(12*(t-1))+604,116,(12*(t-1))+614],
						fill=(0,0,0,255)
					)
					d.rectangle(
						[107,(12*(t-1))+605,115,(12*(t-1))+613],
						fill=pcolor[t-1]
					)
				elif 10 < self.tile[t-1] < 20:
					if t < 5:
						d.rectangle(
							[106,((650-((self.tile[t-1]-10)*50))-47)+(12*(t-1)),116,((650-((self.tile[t-1]-10)*50))-37)+(12*(t-1))],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[107,((650-((self.tile[t-1]-10)*50))-46)+(12*(t-1)),115,((650-((self.tile[t-1]-10)*50))-38)+(12*(t-1))],
							fill=pcolor[t-1]
						)
					else:
						d.rectangle(
							[94,((650-((self.tile[t-1]-10)*50))-47)+(12*(t-5)),104,((650-((self.tile[t-1]-10)*50))-37)+(12*(t-5))],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[95,((650-((self.tile[t-1]-10)*50))-46)+(12*(t-5)),103,((650-((self.tile[t-1]-10)*50))-38)+(12*(t-5))],
							fill=pcolor[t-1]
						)
				elif self.tile[t-1] == 20:
					d.rectangle(
						[138-(12*(t-1)),106,148-(12*(t-1)),116],
						fill=(0,0,0,255)
					)
					d.rectangle(
						[139-(12*(t-1)),107,147-(12*(t-1)),115],
						fill=pcolor[t-1]
					)
				elif 20 < self.tile[t-1] < 30:
					if t < 5:
						d.rectangle(
							[((100+((self.tile[t-1]-20)*50))+39)-(12*(t-1)),106,((100+((self.tile[t-1]-20)*50))+49)-(12*(t-1)),116],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[((100+((self.tile[t-1]-20)*50))+40)-(12*(t-1)),107,((100+((self.tile[t-1]-20)*50))+48)-(12*(t-1)),115],
							fill=pcolor[t-1]
						)
					else:
						d.rectangle(
							[((100+((self.tile[t-1]-20)*50))+39)-(12*(t-5)),94,((100+((self.tile[t-1]-20)*50))+49)-(12*(t-5)),104],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[((100+((self.tile[t-1]-20)*50))+40)-(12*(t-5)),95,((100+((self.tile[t-1]-20)*50))+48)-(12*(t-5)),103],
							fill=pcolor[t-1]
						)
				elif self.tile[t-1] == 30:
					d.rectangle(
						[636,138-(12*(t-1)),646,148-(12*(t-1))],
						fill=(0,0,0,255)
					)
					d.rectangle(
						[637,139-(12*(t-1)),645,147-(12*(t-1))],
						fill=pcolor[t-1]
					)
				elif 30 < self.tile[t-1] < 40:
					if t < 5:
						d.rectangle(
							[636,((100+((self.tile[t-1]-30)*50))+39)-(12*(t-1)),646,((100+((self.tile[t-1]-30)*50))+49)-(12*(t-1))],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[637,((100+((self.tile[t-1]-30)*50))+40)-(12*(t-1)),645,((100+((self.tile[t-1]-30)*50))+48)-(12*(t-1))],
							fill=pcolor[t-1]
						)
					else:
						d.rectangle(
							[648,((100+((self.tile[t-1]-30)*50))+39)-(12*(t-5)),658,((100+((self.tile[t-1]-30)*50))+49)-(12*(t-5))],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[649,((100+((self.tile[t-1]-30)*50))+40)-(12*(t-5)),657,((100+((self.tile[t-1]-30)*50))+48)-(12*(t-5))],
							fill=pcolor[t-1]
						)
			self.imgcache['tile']['image'] = img
		#NUMHOUSE
		if self.imgcache['numhouse']['value'] != self.numhouse:
			self.imgcache['numhouse']['value'] = self.numhouse.copy()
			img = Image.new('RGBA', (750, 750), (0, 0, 0, 0))
			d = ImageDraw.Draw(img)
			for t in range(40):
				if self.numhouse[t] == 5:
					if 0 < t < 10:
						d.rectangle(
							[(650-(t*50))-33,606,(650-(t*50))-15,614],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[(650-(t*50))-32,607,(650-(t*50))-16,613],
							fill=(255,0,0,255)
						)
					elif 10 < t < 20:			
						d.rectangle(
							[138,(650-((t-10)*50))-33,146,(650-((t-10)*50))-17],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[139,(650-((t-10)*50))-32,145,(650-((t-10)*50))-18],
							fill=(255,0,0,255)
						)
					elif 20 < t < 30:
						d.rectangle(
							[(100+((t-20)*50))+17,138,(100+((t-20)*50))+35,146],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[(100+((t-20)*50))+18,139,(100+((t-20)*50))+34,145],
							fill=(255,0,0,255)
						)
					elif 30 < t < 40:
						d.rectangle(
							[606,(100+((t-30)*50))+17,614,(100+((t-30)*50))+35],
							fill=(0,0,0,255)
						)
						d.rectangle(
							[607,(100+((t-30)*50))+18,613,(100+((t-30)*50))+34],
							fill=(255,0,0,255)
						)
				elif self.numhouse[t] > 0:
					for tt in range(self.numhouse[t]):
						if 0 < t < 10:
							d.rectangle(
								[((650-(t*50))-47)+(tt*12),606,((650-(t*50))-37)+(tt*12),614],
								fill=(0,0,0,255)
							)
							d.rectangle(
								[((650-(t*50))-46)+(tt*12),607,((650-(t*50))-38)+(tt*12),613],
								fill=(0,255,0,255)
							)
						elif 10 < t < 20:
							d.rectangle(
								[138,((650-((t-10)*50))-47)+(tt*12),146,((650-((t-10)*50))-37)+(tt*12)],
								fill=(0,0,0,255)
							)
							d.rectangle(
								[139,((650-((t-10)*50))-46)+(tt*12),145,((650-((t-10)*50))-38)+(tt*12)],
								fill=(0,255,0,255)
							)
						elif 20 < t < 30:
							d.rectangle(
								[((100+((t-20)*50))+39)-(tt*12),138,((100+((t-20)*50))+49)-(tt*12),146],
								fill=(0,0,0,255)
							)
							d.rectangle(
								[((100+((t-20)*50))+40)-(tt*12),139,((100+((t-20)*50))+48)-(tt*12),145],
								fill=(0,255,0,255)
							)
						elif 30 < t < 40:
							d.rectangle(
								[606,((100+((t-30)*50))+39)-(tt*12),614,((100+((t-30)*50))+49)-(tt*12)],
								fill=(0,0,0,255)
							)
							d.rectangle(
								[607,((100+((t-30)*50))+40)-(tt*12),613,((100+((t-30)*50))+48)-(tt*12)],
								fill=(0,255,0,255)
							)
			self.imgcache['numhouse']['image'] = img
		#END
		img = Image.open(bundled_data_path(self.cog) / 'img.png')
		for value in self.imgcache.values():
			img.paste(value['image'], box=(0, 0), mask=value['image'])
		temp = BytesIO()
		temp.name = 'board.png'
		img.save(temp)
		temp.seek(0)
		return temp
